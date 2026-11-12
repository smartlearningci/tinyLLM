#!/usr/bin/env python3
"""TinySLM: one local queue, two generation routes, auditable JSONL exports."""
import argparse
import collections
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else dumps(value)).encode()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read_jsonl(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'{path}:{line_no}: {exc}') from exc


def normalize(text):
    return ' '.join(text.casefold().split())


# Abre a fila SQLite e cria apenas tabelas em falta. Mantém os IDs e estados antigos.
def open_db(work):
    work.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(work / 'queue.sqlite')
    db.row_factory = sqlite3.Row
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS recipes(
      id TEXT PRIMARY KEY, hash TEXT UNIQUE, title TEXT, text TEXT, metadata TEXT);
    CREATE TABLE IF NOT EXISTS jobs(
      id TEXT PRIMARY KEY, recipe_id TEXT, persona TEXT, status TEXT,
      attempts INTEGER DEFAULT 0, request TEXT, prompt TEXT, result TEXT,
      provider TEXT, teacher TEXT, usage TEXT, error TEXT, created TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS examples(
      id TEXT PRIMARY KEY, job_id TEXT, recipe_id TEXT, persona TEXT, capability TEXT,
      evidence_type TEXT, status TEXT, content_hash TEXT UNIQUE, data TEXT, review_note TEXT);
    CREATE INDEX IF NOT EXISTS job_state ON jobs(status,created);
    ''')
    return db


# Lê receitas de treino, normaliza separadores e evita duplicados por conteúdo.
def ingest(db, args):
    counts = collections.Counter()
    for record in read_jsonl(args.file):
        meta = record.get('metadata') or {}
        split = meta.get('split') or record.get('split') or meta.get('original_split')
        if split and split != 'train':
            counts['excluded_non_train'] += 1
            continue
        if not split and not args.assume_train:
            raise ValueError('Entrada sem split. Use --assume-train apenas para ficheiro de treino.')
        source = meta.get('source') or record.get('source') or 'imported_recipe'
        if args.source and source != args.source:
            counts['excluded_source'] += 1
            continue
        if meta.get('status') in ('rejected', 'quarantine'):
            counts['excluded_quality'] += 1
            continue
        text = record.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Cada registo necessita de text (string).')
        # Existing corpus has literal backslash-n separators; preserve all other escapes.
        text = text.replace('\\n', '\n').strip()
        h = digest(normalize(text))
        rid = str(record.get('id') or 'recipe:' + h[:20])
        title = meta.get('title') or record.get('title') or text.splitlines()[0][:150]
        meta = {**meta, 'source': source, 'split': 'train', 'import_file': Path(args.file).name}
        existing = db.execute('SELECT hash FROM recipes WHERE id=?', (rid,)).fetchone()
        if existing and existing['hash'] != h:
            raise ValueError(f'ID com texto alterado: {rid}; use uma nova pasta --work.')
        inserted = db.execute('INSERT OR IGNORE INTO recipes VALUES(?,?,?,?,?)',
                              (rid, h, title, text, dumps(meta))).rowcount
        counts['added' if inserted else 'duplicate'] += 1
    db.commit()
    print(dumps(counts))


def task_list(persona_index, recipe_hash):
    # Four rotating content tasks + conversational continuity + missing evidence.
    base = ['C1', 'C2', 'C3', 'C4', 'C5']
    offset = (int(recipe_hash[:8], 16) + persona_index) % len(base)
    caps = [base[(offset+i) % len(base)] for i in range(4)] + ['C6', 'C7']
    focuses = {
        'C1': 'Ask for a concrete ingredient, step, utensil or stated cue.',
        'C2': 'Select the relevant steps or ingredients for a specific practical goal.',
        'C3': 'Relate two supported recipe details; explain an ordering or dependency.',
        'C4': 'Check a specific user preference or constraint against this recipe; avoid guarantees.',
        'C5': 'Reorganise or simplify a specific part, keeping all essential details.',
        'C6': 'Complete conversation with 2–4 exchanges: follow up on an earlier detail and conclude usefully.',
        'C7': 'Ask about a genuinely missing or contradictory detail; answer with calibrated uncertainty.'
    }
    return [{'slot': i, 'capability': cap, 'focus': focuses[cap]} for i, cap in enumerate(caps)]


def choose_notes(recipe, notes, budget):
    words = set(re.findall(r'[a-z]{4,}', recipe['title'].lower() + ' ' + recipe['text'].lower()))
    ranked = []
    for note in notes:
        tags = set(w for tag in note.get('tags', []) for w in re.findall(r'[a-z]{4,}', tag.lower()))
        score = len(words & tags)
        if score:
            ranked.append((-score, note['id'], note))
    chosen, used = [], 0
    for _, _, note in sorted(ranked):
        if used + len(note['text']) <= budget:
            chosen.append({'source_id': note['id'], 'text': note['text'], 'source_url': note['source_url']})
            used += len(note['text'])
        if len(chosen) == 2:
            break
    return chosen


# Cria um pedido por receita e persona. Guarda o prompt completo para reprodução.
def plan(db, args, config):
    notes = list(read_jsonl(args.knowledge)) if args.knowledge else []
    for n in notes:
        if not all(isinstance(n.get(k), str) and n[k].strip() for k in ('id','text','source_url')):
            raise ValueError('Knowledge requer id, text, source_url não vazios e tags.')
        if not isinstance(n.get('tags'), list) or not all(isinstance(t,str) for t in n['tags']):
            raise ValueError('Knowledge tags deve ser lista de strings.')
    if len({n['id'] for n in notes}) != len(notes):
        raise ValueError('Knowledge ids repetidos.')
    template = (ROOT / 'prompt.txt').read_text()
    rows = db.execute('SELECT * FROM recipes ORDER BY hash LIMIT ?', (args.limit,)).fetchall()
    definitions = {x['id']: x for x in config['capabilities']}
    added = skipped = 0
    for recipe in rows:
        if len(recipe['text']) > config['max_recipe_chars']:
            skipped += 1
            continue  # Never silently truncate ingredients/method.
        knowledge = choose_notes(recipe, notes, config['max_knowledge_chars'])
        if any(n['source_id'] == recipe['id'] for n in knowledge):
            raise ValueError('IDs de knowledge colidem com receita.')
        for i, persona in enumerate(config['personas']):
            if db.execute('SELECT 1 FROM jobs WHERE recipe_id=? AND persona=?', (recipe['id'],persona['id'])).fetchone():
                continue
            tasks = task_list(i, recipe['hash'])
            request = {
                'version': config['version'], 'conversation_policy':'complete-v3', 'language':'en', 'persona':persona,
                'recipe': {'source_id':recipe['id'], 'title':recipe['title'], 'text':recipe['text']},
                'knowledge': knowledge, 'tasks':tasks,
                'capabilities': [definitions[c] for c in dict.fromkeys(t['capability'] for t in tasks)]
            }
            jid = digest({'request':request, 'prompt':template})[:24]
            request['job_id'] = jid
            prompt = template + '\nREQUEST\n' + dumps(request) + '\n'
            added += db.execute('''INSERT OR IGNORE INTO jobs
                (id,recipe_id,persona,status,request,prompt,created,updated)
                VALUES(?,?,?,'pending',?,?,?,?)''',
                (jid,recipe['id'],persona['id'],dumps(request),prompt,now(),now())).rowcount
    db.commit()
    print(dumps({'recipes_selected':len(rows),'too_long':skipped,'new_jobs':added,'target_examples':added*6}))


def sources_for(request):
    return {x['source_id']:x['text'] for x in [request['recipe'],*request['knowledge']]}


def response_schema():
    return json.loads((ROOT/'response.schema.json').read_text())


def validate_json(value, schema, path='$'):
    """Validate the small JSON Schema subset used by this package (no dependencies)."""
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    expected = types[schema['type']]
    if type(value) is not expected:
        raise ValueError(f'{path}: esperado {schema["type"]}.')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: valor fora do enum.')
    if expected is dict:
        if set(value) != set(schema['required']):
            raise ValueError(f'{path}: campos em falta ou adicionais.')
        for key, item in value.items():
            validate_json(item, schema['properties'][key], path+'.'+key)
    elif expected is list:
        for i, item in enumerate(value):
            validate_json(item, schema['items'], path+f'[{i}]')


# Confirma esquema, tarefas, turnos e citações. Não avalia a verdade semântica.
def validate_response(raw, request):
    validate_json(raw, response_schema())
    if raw['job_id'] != request['job_id']:
        raise ValueError('job_id não corresponde ao pedido.')
    expected = {t['slot']:t['capability'] for t in request['tasks']}
    if sorted(e['slot'] for e in raw['examples']) != sorted(expected):
        raise ValueError('Slots em falta ou repetidos: esperado exactamente um por tarefa.')
    sources = sources_for(request)
    for e in raw['examples']:
        if e['capability'] != expected[e['slot']]:
            raise ValueError('Capacidade diferente da tarefa.')
        if not e['supported']:
            if e['messages'] or e['evidence'] or not e['evidence_note'].strip():
                raise ValueError('Slot unsupported deve ter arrays vazios e motivo.')
            continue
        roles = [m['role'] for m in e['messages']]
        turns = len(roles) // 2
        minimum = 2 if e['capability']=='C6' else 1
        if not minimum <= turns <= 4 or roles != ['user','assistant'] * turns:
            raise ValueError('Ordem de mensagens inválida.')
        if e['capability']=='C7' and e['evidence_type']!='E0':
            raise ValueError('C7 deve testar ausência/conflito de evidência (E0).')
        if not e['evidence'] or len(e['evidence']) > 3:
            raise ValueError('São necessárias 1–3 citações de suporte.')
        for ev in e['evidence']:
            if ev['source_id'] not in sources or not ev['quote'].strip():
                raise ValueError('Fonte ou citação inválida.')
            if normalize(ev['quote']) not in normalize(sources[ev['source_id']]):
                raise ValueError('Citação não existe na fonte indicada.')
        if e['evidence_type']=='E4' and not any(ev['source_id'] != request['recipe']['source_id'] for ev in e['evidence']):
            raise ValueError('E4 necessita de suporte de uma nota externa anexada.')
        if e['evidence_type'] in ('E1','E2') and any(ev['source_id'] != request['recipe']['source_id'] for ev in e['evidence']):
            raise ValueError('Usou nota externa: deve marcar E4.')
        for msg in e['messages']:
            if len(msg['content'].strip()) < 5:
                raise ValueError('Mensagem vazia/curta.')
            words = re.findall(r'\w+',msg['content'].casefold())
            grams = [' '.join(words[i:i+8]) for i in range(max(0,len(words)-7))]
            if grams and max(collections.Counter(grams).values()) >= 3:
                raise ValueError('Repetição excessiva de sequência de palavras.')
    return raw


def parse_response(text):
    text = text.strip().lstrip('\ufeff')
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[-1].strip() != '```':
            raise ValueError('Bloco Markdown incompleto.')
        text = '\n'.join(lines[1:-1])
    return json.loads(text)


# Valida a resposta antes de gravar conversas e concluir o pedido na mesma transação.
def store_response(db, job, raw, provider, teacher, usage=None):
    request = json.loads(job['request'])
    validate_response(raw,request)
    added = duplicate = unsupported = 0
    with db:
        for e in raw['examples']:
            if not e['supported']:
                unsupported += 1
                continue
            # Across all sources/personas/providers, exact conversation duplicates retained once.
            h = digest(normalize(dumps(e['messages'])))
            eid = job['id'] + ':' + str(e['slot'])
            status = 'needs_review' if e['evidence_type']=='E4' else 'auto_valid'
            inserted = db.execute('INSERT OR IGNORE INTO examples VALUES(?,?,?,?,?,?,?,?,?,?)',
                (eid,job['id'],job['recipe_id'],job['persona'],e['capability'],e['evidence_type'],status,h,dumps(e),'')).rowcount
            added += inserted
            duplicate += 1-inserted
        db.execute("UPDATE jobs SET status='done',result=?,provider=?,teacher=?,usage=?,error=NULL,updated=? WHERE id=?",
                   (dumps(raw),provider,teacher,dumps(usage) if usage else None,now(),job['id']))
    return {'added':added,'duplicate':duplicate,'unsupported':unsupported}


def upgrade_prompts(db, args, work):
    backup = work / ('queue-before-v3-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite')
    with sqlite3.connect(backup) as target:
        db.backup(target)
    template = (ROOT/'prompt.txt').read_text(encoding='utf-8')
    count = 0
    states = ('pending','error','manual') if getattr(args,'include_manual',False) else ('pending','error')
    marks = ','.join('?' for _ in states)
    for job in db.execute(f'SELECT * FROM jobs WHERE status IN ({marks})',states).fetchall():
        req = json.loads(job['request'])
        if req.get('conversation_policy') == 'complete-v3':
            continue
        req['conversation_policy'] = 'complete-v3'
        for task in req['tasks']:
            if task['capability'] == 'C6':
                task['focus'] = 'Complete conversation with 2–4 exchanges and a useful conclusion.'
        db.execute('UPDATE jobs SET request=?,prompt=?,updated=? WHERE id=?',
                   (dumps(req), template+'\nREQUEST\n'+dumps(req)+'\n',now(),job['id']))
        count += 1
    db.commit()
    print(f'{count} pedidos atualizados. Backup: {backup}. Resultados concluídos preservados. Reexporte os prompts das reservas que atualizou.')


# Reserva pedidos para o chat: o gerador CLI deixa de os selecionar.
def export_prompts(db, args):
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    clauses = ['status=?']; values = [getattr(args,'status','pending')]
    for flag, column in [('persona','persona'),('recipe','recipe_id'),('job','id')]:
        value = getattr(args,flag,None)
        if value:
            clauses.append(column+'=?');values.append(value)
    provider = getattr(args,'provider','copilot')
    if getattr(args,'status','pending') == 'manual':
        clauses.append('provider=?');values.append(provider)
    values.append(args.limit)
    rows = db.execute('SELECT * FROM jobs WHERE '+' AND '.join(clauses)+' ORDER BY created,id LIMIT ?',values).fetchall()
    batch_size = getattr(args,'batch_size',1)
    files = []
    for start in range(0,len(rows),batch_size):
        group = rows[start:start+batch_size]
        if batch_size == 1:
            name = group[0]['id']+'.txt'; text = group[0]['prompt']
        else:
            # One common instruction block per distinct policy, not per recipe.
            templates = list(dict.fromkeys(j['prompt'].split('\nREQUEST\n',1)[0] for j in group))
            if len(templates) != 1:
                raise ValueError('Lote mistura versões de prompts. Exporte essas reservas individualmente.')
            name = 'batch-'+digest([j['id'] for j in group])[:16]+'.txt'
            text = templates[0] + '\nBATCH OVERRIDE: Process every request below independently. Return ONLY a JSON array of response objects, one per job_id, using the single-response format above for each object. Include all task slots. Never merge jobs.\nREQUESTS\n' + dumps([json.loads(j['request']) for j in group])+'\n'
        (out/name).write_text(text,encoding='utf-8');files.append(name)
    with db:
        for job in rows:
            db.execute("UPDATE jobs SET status='manual',provider=?,updated=? WHERE id=?",(provider,now(),job['id']))
    print(f'{len(rows)} pedidos reservados para {provider} em {out}.')
    for name in files: print(name)


# Importa ficheiros ou lotes JSON; pedidos concluídos não são importados de novo.
def import_responses(db, args, work):
    source = Path(args.path)
    paths = sorted(source.glob('*.json')) if source.is_dir() else [source]
    if not paths:
        raise ValueError('Não foram encontrados ficheiros .json.')
    errors = 0
    for path in paths:
        try:
            text = path.read_text(encoding='utf-8-sig')
            parsed = parse_response(text)
            items = parsed if isinstance(parsed,list) else [parsed]
            if not items:
                raise ValueError('Lote vazio.')
        except (ValueError,OSError) as exc:
            errors += 1;print(f'{path.name}: INVALIDO: {exc}',file=sys.stderr);continue
        for index,raw in enumerate(items):
            label = f'{path.name}[{index}]'
            try:
                if not isinstance(raw,dict) or not isinstance(raw.get('job_id'),str):
                    raise ValueError('Cada resposta necessita de job_id.')
                jid = raw['job_id']
                job = db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
                if not job:
                    raise ValueError('job_id desconhecido; use a fila que criou o pedido.')
                if job['status']=='done':
                    print(label+': já importado; ignorado.');continue
                raw_dir=work/'raw';raw_dir.mkdir(exist_ok=True)
                (raw_dir/(jid+'-manual-'+digest(text)[:12]+'.json')).write_text(text,encoding='utf-8')
                print(label,jid,store_response(db,job,raw,args.provider,args.teacher))
            except ValueError as exc:
                errors += 1
                print(label+': INVALIDO: '+str(exc).splitlines()[0],file=sys.stderr)
    if errors:
        raise ValueError(f'{errors} respostas inválidas; respostas válidas guardadas; corrija e reimporte o ficheiro.')


# Executa uma chamada por pedido e arquiva resposta e logs. Para no primeiro erro.
def run_codex(db, args, config, work):
    executable = shutil.which(args.codex_bin)
    if not executable:
        raise ValueError('Codex CLI não encontrado. Instale/autentique antes de executar run.')
    if os.getenv('CODEX_API_KEY') or os.getenv('OPENAI_API_KEY'):
        raise ValueError('Existe uma API key no ambiente. Execute num terminal sem essas variáveis para usar a sessão ChatGPT.')
    auth = subprocess.run([executable,'login','status'],capture_output=True,text=True,timeout=30)
    if auth.returncode or 'chatgpt' not in (auth.stdout+auth.stderr).casefold():
        raise ValueError('Não foi confirmada autenticação ChatGPT. Execute codex login e codex login status.')
    help_result = subprocess.run([executable,'exec','--help'],capture_output=True,text=True,timeout=30)
    if '--output-schema' not in help_result.stdout:
        raise ValueError('CLI sem --output-schema: atualizar Codex CLI.')
    raw_dir = work/'raw';raw_dir.mkdir(exist_ok=True)
    completed = 0
    for _ in range(args.limit):
        job = db.execute("SELECT * FROM jobs WHERE status='pending' AND attempts<? ORDER BY created,id LIMIT 1",(config['max_attempts'],)).fetchone()
        if not job:
            break
        attempt = job['attempts']+1
        db.execute("UPDATE jobs SET status='running',attempts=?,provider='codex',updated=? WHERE id=?",(attempt,now(),job['id']));db.commit()
        stem=raw_dir/(job['id']+f'-{attempt}')
        try:
            # Fresh session, empty working directory: no project files or previous conversation.
            with tempfile.TemporaryDirectory(prefix='tinyslm-distill-') as folder:
                output=Path(folder)/'response.json'
                cmd=[executable,'--ask-for-approval','never','exec','--sandbox','read-only',
                     '--skip-git-repo-check','--output-schema',str(ROOT/'response.schema.json'),
                     '--json','-o',str(output)]
                if '--ephemeral' in help_result.stdout:
                    cmd.append('--ephemeral')
                model=args.model or config.get('codex_model')
                if model:
                    cmd.extend(['--model',model])
                cmd.append('-')
                started=time.monotonic()
                with stem.with_suffix('.events.jsonl').open('w') as log, stem.with_suffix('.stderr.txt').open('w') as err:
                    proc=subprocess.run(cmd,input=job['prompt'],text=True,stdout=log,stderr=err,cwd=folder,
                                        timeout=config['timeout_seconds'])
                if proc.returncode:
                    raise ValueError(f'Codex terminou com código {proc.returncode}; ver {stem.name}.stderr.txt')
                text=output.read_text(encoding='utf-8')
                stem.with_suffix('.response.json').write_text(text,encoding='utf-8')
            usage={'elapsed_seconds':round(time.monotonic()-started,2)}
            for line in stem.with_suffix('.events.jsonl').read_text().splitlines():
                try:
                    event=json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('type')=='turn.completed' and event.get('usage'):
                    usage.update(event['usage'])
            result=store_response(db,job,parse_response(text),'codex',model or 'CLI default (see events)',usage)
            completed+=1
            print(job['id'],dumps(result),flush=True)
        except KeyboardInterrupt:
            db.execute("UPDATE jobs SET status='error',error='Interrupted; inspect raw output before retry',updated=? WHERE id=?",(now(),job['id']));db.commit()
            raise
        except Exception as exc:
            db.execute("UPDATE jobs SET status='error',error=?,updated=? WHERE id=?",(str(exc),now(),job['id']));db.commit()
            # Stop at first failure: quotas/auth/schema errors must not burn the queue.
            raise ValueError(f'Fila pausada: {exc}. Corrigir e usar retry.') from exc
    print(f'Concluídos nesta execução: {completed}.')


# Devolve pedidos elegíveis à fila, respeitando o máximo de tentativas.
def retry(db,args,config):
    if args.job:
        rows=db.execute('SELECT * FROM jobs WHERE id=?',(args.job,)).fetchall()
    else:
        rows=db.execute("SELECT * FROM jobs WHERE status='error'").fetchall()
    changed=0
    for row in rows:
        if row['status'] in ('error','manual') and row['attempts']<config['max_attempts']:
            db.execute("UPDATE jobs SET status='pending',error=NULL,updated=? WHERE id=?",(now(),row['id']));changed+=1
    db.commit();print(f'{changed} pedidos pendentes. Limite: {config["max_attempts"]} tentativas Codex/pedido.')


# Guarda a decisão humana e a nota sem alterar a conversa original.
def review(db,args):
    changed=db.execute('UPDATE examples SET status=?,review_note=? WHERE id=?',(args.decision,args.note,args.id)).rowcount
    db.commit()
    if not changed:
        raise ValueError('Exemplo não encontrado.')
    print('Revisão guardada.')


# Exporta contexto e conversas. Estes ficheiros ainda não têm divisão treino/validação.
def export_data(db,args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    statuses=['accepted'] if args.reviewed_only else ['accepted','auto_valid']
    placeholders=','.join('?' for _ in statuses)
    rows=db.execute(f'''SELECT e.*,j.request,j.provider,j.teacher,j.created,j.usage,r.metadata
       FROM examples e JOIN jobs j ON e.job_id=j.id JOIN recipes r ON r.id=e.recipe_id
       WHERE e.status IN ({placeholders}) ORDER BY e.id''',statuses)
    count=0
    with (out/'candidates.jsonl').open('w') as rich,(out/'sft_train.jsonl').open('w') as sft,(out/'text_train.jsonl').open('w') as plain:
        for row in rows:
            e=json.loads(row['data']);req=json.loads(row['request'])
            # Preserve full recipe context. Only attach knowledge actually quoted by the teacher.
            used={ev['source_id'] for ev in e['evidence']}
            chunks=[req['recipe']]+[k for k in req['knowledge'] if k['source_id'] in used]
            context='\n\n'.join(c['text'] for c in chunks)
            messages=[{'role':'system','content':'Answer culinary questions in English using the supplied context. State missing information clearly.'},
                      *[dict(m) for m in e['messages']]]
            messages[1]['content']='Recipe context:\n'+context+'\n\nQuestion: '+messages[1]['content']
            record={'id':row['id'],'recipe_id':row['recipe_id'],'split':'train','synthetic':True,
                    'persona':row['persona'],'capability':row['capability'],'evidence_type':row['evidence_type'],
                    'validation_status':row['status'],'review_note':row['review_note'],
                    'provenance':{'provider':row['provider'],'teacher':row['teacher'],'source':json.loads(row['metadata']),
                                  'job_id':row['job_id'],'version':req['version']},
                    'context':{'chunks':chunks},'conversation':e['messages'],
                    'evidence':e['evidence'],'evidence_note':e['evidence_note'],'difficulty':e['difficulty']}
            rich.write(dumps(record)+'\n')
            sft.write(dumps({'id':row['id'],'messages':messages})+'\n')
            text='Recipe context:\n'+context+'\n\n'+'\n\n'.join(('Question: ' if m['role']=='user' else 'Answer: ')+m['content'] for m in e['messages'])
            plain.write(dumps({'id':row['id'],'text':text,'metadata':{'synthetic':True,'recipe_id':row['recipe_id'],'status':row['status']}})+'\n')
            count+=1
    write_json(out/'manifest.json',{'created':now(),'examples':count,'statuses':statuses,'split':'train',
      'factual_accuracy_checked':False,'historical_overlap_checked':False,
      'notes':['SFT and text are alternative exports of the same examples, not two independent corpora.',
               'No truncation: measure with the student tokenizer before training.',
               'Original recipe validation/benchmark are not generated or exported. No synthetic validation split.']})
    print(f'{count} exemplos exportados em {out}. E4 pendente de revisão excluído.')


# Produz uma fotografia do progresso. O painel web lê a fila atual diretamente.
def report(db,args):
    jobs=dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall())
    statuses=dict(db.execute('SELECT status,count(*) FROM examples GROUP BY status').fetchall())
    matrix=[dict(r) for r in db.execute("SELECT persona,capability,count(*) AS n FROM examples WHERE status!='rejected' GROUP BY persona,capability")]
    lengths=[]
    for row in db.execute("SELECT data FROM examples WHERE status!='rejected'"):
        e=json.loads(row['data']);lengths.append(sum(len(m['content']) for m in e['messages']))
    usage=collections.Counter()
    for row in db.execute('SELECT usage FROM jobs WHERE usage IS NOT NULL'):
        for k,v in json.loads(row['usage']).items():
            if isinstance(v,(int,float)):usage[k]+=v
    stats={'created':now(),'recipes':db.execute('SELECT count(*) FROM recipes').fetchone()[0],
           'jobs':jobs,'examples':statuses,'coverage':matrix,'usage':dict(usage),
           'qa_characters':sum(lengths),'qa_tokens_estimated_chars_div4':round(sum(lengths)/4),
           'token_estimate_excludes_recipe_context':True}
    samples=[dict(r) for r in db.execute('''SELECT e.*,r.title FROM examples e JOIN recipes r ON e.recipe_id=r.id
              ORDER BY e.persona,e.capability,e.id LIMIT 500''')]
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    write_json(out/'report.json',stats)
    payload=dumps({'stats':stats,'samples':samples}).replace('<','\\u003c')
    template=(ROOT/'report_template.html').read_text()
    (out/'report.html').write_text(template.replace('__PAYLOAD__',payload),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    print('Painel:',out/'report.html')


def status(work):
    """Inspect the live queue without acquiring the writer lock or changing state."""
    path = work / 'queue.sqlite'
    if not path.is_file():
        raise ValueError(f'Fila não encontrada: {path}. Indique --work com a pasta existente.')
    with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        print('Fila:', path)
        print('Receitas:', db.execute('SELECT count(*) FROM recipes').fetchone()[0])
        print('Receitas com pedidos:', db.execute('SELECT count(DISTINCT recipe_id) FROM jobs').fetchone()[0])
        print('Receitas com pedidos concluídos:', db.execute("SELECT count(DISTINCT recipe_id) FROM jobs WHERE status='done'").fetchone()[0])
        for table, label in [('jobs', 'Pedidos'), ('examples', 'Conversas')]:
            print('\n'+label+' por estado:')
            for state, count in db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status ORDER BY status'):
                print(f'  {state}: {count}')
        print('\nÚltimos erros:')
        for jid, error in db.execute("SELECT id,error FROM jobs WHERE status='error' ORDER BY updated DESC LIMIT 3"):
            print(f'  {jid}: {error}')


# Interpreta comandos e bloqueia operações concorrentes de escrita na mesma fila.
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',default=str(ROOT/'dados'),help='Pasta de estado; reutilizar para retoma.')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status',help='Consultar progresso durante a geração, sem alterar a fila.')
    p=sub.add_parser('ingest');p.add_argument('file');p.add_argument('--source',default='recipe_nlg_lite');p.add_argument('--assume-train',action='store_true')
    p=sub.add_parser('plan');p.add_argument('--limit',type=int,default=100);p.add_argument('--knowledge')
    p=sub.add_parser('run');p.add_argument('--limit',type=int,default=10);p.add_argument('--model');p.add_argument('--codex-bin',default='codex')
    p=sub.add_parser('prompts');p.add_argument('--limit',type=int,default=2);p.add_argument('--out',default=str(ROOT/'dados'/'prompts'))
    p.add_argument('--batch-size',type=int,default=1);p.add_argument('--persona',choices=['P1','P2','P3','P4','P5']);p.add_argument('--recipe');p.add_argument('--job');p.add_argument('--status',choices=['pending','manual'],default='pending')
    p.add_argument('--provider',default='chatgpt',help='Fornecedor das novas reservas ou filtro das reservas manual.')
    p=sub.add_parser('upgrade');p.add_argument('--include-manual',action='store_true',help='Atualiza também reservas; reexportar os seus prompts depois.')
    p=sub.add_parser('import');p.add_argument('path');p.add_argument('--provider',default='chatgpt');p.add_argument('--teacher',default='chatgpt-manual')
    p=sub.add_parser('retry');p.add_argument('--job')
    p=sub.add_parser('review');p.add_argument('id');p.add_argument('decision',choices=['accepted','rejected','needs_review']);p.add_argument('--note',default='')
    p=sub.add_parser('export');p.add_argument('--out',default=str(ROOT/'dados'/'exports'));p.add_argument('--reviewed-only',action='store_true')
    p=sub.add_parser('report');p.add_argument('--out',default=str(ROOT/'dados'/'report'))
    args=parser.parse_args(argv)
    if hasattr(args,'limit') and args.limit<1:
        parser.error('--limit deve ser positivo.')
    if hasattr(args,'batch_size') and args.batch_size<1:
        parser.error('--batch-size deve ser positivo.')
    work=Path(args.work).resolve()
    if args.command=='status':
        status(work)
        return
    work.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'config.json').read_text())
    # One writer: prevents a second terminal/Claw process from duplicating paid jobs.
    with (work/'queue.lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Outra operação usa esta fila. Aguarde a sua conclusão.')
        with contextlib.closing(open_db(work)) as db:
            db.execute("UPDATE jobs SET status='error',error='Interrupted previous process; inspect raw before retry' WHERE status='running'");db.commit()
            if args.command=='ingest':ingest(db,args)
            elif args.command=='plan':plan(db,args,config)
            elif args.command=='run':run_codex(db,args,config,work)
            elif args.command=='upgrade':upgrade_prompts(db,args,work)
            elif args.command=='prompts':export_prompts(db,args)
            elif args.command=='import':import_responses(db,args,work)
            elif args.command=='retry':retry(db,args,config)
            elif args.command=='review':review(db,args)
            elif args.command=='export':export_data(db,args)
            elif args.command=='report':report(db,args)


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nParado; resultados concluídos preservados.',file=sys.stderr);sys.exit(130)
    except Exception as exc:
        print(f'ERRO: {exc}',file=sys.stderr);sys.exit(1)
