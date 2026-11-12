#!/usr/bin/env python3
"""Copiar o projeto antigo e preparar datasets Kaggle, sem dependências externas."""
import argparse
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import distill

ROOT = Path(__file__).resolve().parent


def migrar(origem):
    """Copia uma vez. O destino nunca pode substituir uma fila já existente."""
    origem = Path(origem).expanduser().resolve()
    source = origem/'work'/'queue.sqlite'
    target = ROOT/'dados'/'queue.sqlite'
    if not source.is_file():
        raise ValueError(f'Não existe {source}')
    if target.exists():
        raise ValueError('Já existe dados/queue.sqlite. Migração recusada para preservar o progresso.')
    target.parent.mkdir(exist_ok=True)
    # O gerador antigo usa este mesmo lock. Aguarde que termine antes de migrar.
    with (source.parent/'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        # A API backup copia uma fotografia coerente, incluindo dados no WAL.
        temporary=target.with_suffix('.migrating')
        try:
            with contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old:
                with contextlib.closing(sqlite3.connect(temporary)) as new:
                    old.backup(new)
                    if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('A cópia da base não passou a verificação de integridade.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        # Logs são opcionais para operar, mas úteis para manter a proveniência.
        if (source.parent/'raw').exists():
            shutil.copytree(source.parent/'raw',target.parent/'raw',dirs_exist_ok=True)
        recipes=origem/'data'/'recipes_train.jsonl'
        if recipes.exists(): shutil.copy2(recipes,target.parent/'receitas.jsonl')
        # Preserva respostas externas ainda não importadas e prompts já reservados.
        for p in origem.iterdir():
            if p.is_dir() and p.name.startswith(('respostas','prompts','lotes')):
                shutil.copytree(p,target.parent/'arquivo_antigo'/p.name,dirs_exist_ok=True)
    distill.status(target.parent)
    print('Cópia independente concluída. O projeto antigo não foi alterado.')


def grupo(row):
    """Chaves de receita: ID, grupo de origem e texto normalizado evitam fuga entre splits."""
    keys={'id:'+row['recipe_id']}
    source=row.get('provenance',{}).get('source',{})
    for k in ('group_id','source_group_id'):
        if source.get(k): keys.add(k+':'+str(source[k]))
    for c in row['context']['chunks'][:1]:
        keys.add('text:'+distill.digest(distill.normalize(c['text'])))
    return keys


def treino(validation, nome):
    """Cria um pacote novo; preserva byte a byte a validação escolhida pelo utilizador."""
    validation=Path(validation).expanduser().resolve()
    if not validation.is_file(): raise ValueError('Indique o validation_v01.jsonl da experiência anterior.')
    if not nome or Path(nome).name != nome or nome in ('.','..'):
        raise ValueError('O nome deve ser apenas um nome de pasta, por exemplo culinario_v03.')
    out=ROOT/'dados'/'exports'/nome
    if out.exists(): raise ValueError('Esta versão já existe; escolha um novo nome.')
    val=list(distill.read_jsonl(validation))
    if not val: raise ValueError('Validação vazia.')
    reserved=set().union(*(grupo(r) for r in val))
    work=ROOT/'dados'
    if not (work/'queue.sqlite').is_file(): raise ValueError('Importe a fila antes de preparar treino.')
    with (work/'queue.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.closing(sqlite3.connect((work/'queue.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                distill.export_data(db,argparse.Namespace(out=tmp,reviewed_only=False))
            rows=list(distill.read_jsonl(Path(tmp)/'candidates.jsonl'))
    # Fecho transitivo: uma receita ligada a uma reservada também fica reservada.
    changed=True
    while changed:
        before=len(reserved)
        for r in rows:
            if grupo(r)&reserved: reserved.update(grupo(r))
        changed=len(reserved)!=before
    train=[r for r in rows if not grupo(r)&reserved and r['provenance']['provider']!='chatgpt-demo']
    if not train: raise ValueError('Não há conversas elegíveis para treino.')
    # Usa o mesmo formato esperado pelo notebook; nomes genéricos em cada versão.
    out.mkdir(parents=True)
    for r in train: r['split']='train'
    (out/'train.jsonl').write_text(''.join(distill.dumps(r)+'\n' for r in train),encoding='utf-8')
    shutil.copy2(validation,out/'validation.jsonl')
    report={'version':nome,'train_examples':len(train),'validation_examples':len(val),
            'train_recipes':len({r['recipe_id'] for r in train}),
            'validation_recipes':len({r['recipe_id'] for r in val}),
            'validation_sha256':hashlib.sha256(validation.read_bytes()).hexdigest(),
            'train_sha256':hashlib.sha256((out/'train.jsonl').read_bytes()).hexdigest(),
            'excluded_examples':len(rows)-len(train),
            'note':'Validação preservada; demo e receitas/grupos/textos da validação excluídos do treino.'}
    distill.write_json(out/'dataset_report.json',report)
    print(json.dumps(report,indent=2));print('Carregar estes três ficheiros no Kaggle:',out)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('migrar');p.add_argument('origem')
    p=sub.add_parser('treino');p.add_argument('--validation',required=True);p.add_argument('--nome',required=True)
    args=parser.parse_args()
    try:
        if args.command=='migrar': migrar(args.origem)
        else: treino(args.validation,args.nome)
    except (ValueError,OSError,sqlite3.Error) as exc:
        parser.exit(1,f'ERRO: {exc}\n')
