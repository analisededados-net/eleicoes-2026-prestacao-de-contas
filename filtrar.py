#!/usr/bin/env python3
"""Extrai contas dos dois candidatos sem escrever nos arquivos de origem."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unicodedata


DEFAULT_SOURCE = Path('/mnt/multimidia/Dados/politica/eleicoes-2026/prestacao-de-contas')
TARGETS = {
    'lula': 'LUIZ INACIO LULA DA SILVA',
    'flavio-bolsonaro': 'FLAVIO NANTES BOLSONARO',
}
DIRECT = [
    'prestacao_de_contas_eleitorais_candidatos_2026/receitas_candidatos_2026_BRASIL.csv',
    'prestacao_de_contas_eleitorais_candidatos_2026/despesas_contratadas_candidatos_2026_BRASIL.csv',
    'despesa_documento_2026/despesa_candidato_documento_2026_BRASIL.csv',
    'receita_documento_2026/receita_candidato_documento_2026_BRASIL.csv',
    'extrato_bancario_candidato_2026/extrato_bancario_candidato_2026.csv',
]
INDIRECT = [
    'prestacao_de_contas_eleitorais_candidatos_2026/despesas_pagas_candidatos_2026_BRASIL.csv',
    'prestacao_de_contas_eleitorais_candidatos_2026/receitas_candidatos_doador_originario_2026_BRASIL.csv',
]
CNPJ = 'CNPJ_campanha_2026/cnpj_candidatos_2026.txt'
ID_FIELDS = ('SQ_CANDIDATO', 'SQ_PRESTADOR_CONTAS', 'NR_CNPJ_PRESTADOR_CONTA')


def normalize(value):
    return ' '.join(''.join(
        c for c in unicodedata.normalize('NFKD', value.upper())
        if not unicodedata.combining(c)
    ).split())


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def usable(value):
    return bool(value) and value not in ('#NULO', '#NE', '-1', '-3', '0')


def identify(row):
    names = {normalize(row.get(key, '')) for key in ('NM_CANDIDATO', 'NM_PRESTADOR_CONTA')}
    matches = [slug for slug, name in TARGETS.items() if name in names]
    if len(matches) > 1:
        raise ValueError('Registro com nomes de candidatos conflitantes')
    return matches[0] if matches else None


def filter_csv(source, destination, relative, identities, indirect=False):
    from contextlib import ExitStack

    counts = Counter()
    turns = {slug: Counter() for slug in TARGETS}
    scanned = 0
    with ExitStack() as stack:
        stream = stack.enter_context((source / relative).open(encoding='latin1', newline=''))
        reader = csv.DictReader(stream, delimiter=';')
        header = reader.fieldnames
        writers = {}
        for slug in TARGETS:
            output = destination / slug / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(output.open('x', encoding='utf-8', newline=''))
            writers[slug] = csv.DictWriter(handle, fieldnames=header, delimiter=';', quoting=csv.QUOTE_ALL)
            writers[slug].writeheader()
        for row in reader:
            scanned += 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Linha CSV inválida: {relative}, registro {scanned}')
            if indirect:
                matches = [slug for slug in TARGETS
                           if row.get('SQ_PRESTADOR_CONTAS') in identities[slug]['SQ_PRESTADOR_CONTAS']]
                if len(matches) > 1:
                    raise ValueError('Identificador de prestador compartilhado pelos dois candidatos')
                slug = matches[0] if matches else None
            else:
                slug = identify(row)
            if slug is None:
                continue
            year = row.get('AA_ELEICAO', row.get('ANO_ELEICAO', row.get('AA_REFERENCIA')))
            if year != '2026':
                raise ValueError(f'Ano inesperado no registro selecionado: {year}')
            if not indirect:
                for field in ID_FIELDS:
                    value = row.get(field, '')
                    if usable(value):
                        identities[slug][field].add(value)
            writers[slug].writerow(row)
            counts[slug] += 1
            if 'ST_TURNO' in row:
                turns[slug][row['ST_TURNO']] += 1
    print(f'{Path(relative).name}: lidos={scanned}, selecionados={dict(counts)}', flush=True)
    return {'origem': relative, 'registros_lidos': scanned,
            'selecionados': {slug: counts[slug] for slug in TARGETS},
            'turnos': {slug: dict(turns[slug]) for slug in TARGETS},
            'criterio': 'SQ_PRESTADOR_CONTAS' if indirect else 'nome completo do titular'}


def filter_cnpj(source, destination, identities):
    selected = {slug: [] for slug in TARGETS}
    with (source / CNPJ).open(encoding='latin1', newline='') as stream:
        header = stream.readline().rstrip('\r\n')
        for line in stream:
            record = line.rstrip('\r\n')
            if not record.startswith('2'):
                continue
            for slug in TARGETS:
                if record[3:17] in identities[slug]['NR_CNPJ_PRESTADOR_CONTA']:
                    selected[slug].append(record)
    result = {}
    for slug, records in selected.items():
        if not records:
            raise ValueError(f'CNPJ de campanha não localizado: {slug}')
        path = destination / slug / CNPJ
        path.parent.mkdir(parents=True, exist_ok=True)
        trailer = '9' + str(len(records)).zfill(9) + ' ' * 190
        with path.open('x', encoding='latin1', newline='') as stream:
            stream.write('\r\n'.join([header, *records, trailer]))
        result[slug] = len(records)
    return {'origem': CNPJ, 'selecionados': result,
            'criterio': 'CNPJ do titular; trailer recalculado conforme leiaute TSE'}


def run(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError('A saída deve ficar fora da pasta dos dados brutos')
    inputs = DIRECT + INDIRECT + [CNPJ]
    for relative in inputs:
        if not (source / relative).is_file():
            raise FileNotFoundError(source / relative)
    # Não reutilizar uma saída existente: evita sobrescritas e misturas de execuções.
    destination.mkdir(parents=True, exist_ok=False)
    before = {relative: digest(source / relative) for relative in inputs}
    identities = {slug: {key: set() for key in ID_FIELDS} for slug in TARGETS}
    results = [filter_csv(source, destination, relative, identities) for relative in DIRECT]
    for slug in TARGETS:
        if not identities[slug]['SQ_PRESTADOR_CONTAS']:
            raise ValueError(f'Não foi possível identificar a prestação de contas de {slug}')
    for field in ID_FIELDS:
        if identities['lula'][field] & identities['flavio-bolsonaro'][field]:
            raise ValueError(f'Identificador compartilhado: {field}')
    results.extend(filter_csv(source, destination, relative, identities, indirect=True)
                   for relative in INDIRECT)
    results.append(filter_cnpj(source, destination, identities))
    after = {relative: digest(source / relative) for relative in inputs}
    if before != after:
        raise RuntimeError('Os arquivos de origem mudaram durante o processamento')
    outputs = {str(path.relative_to(destination)): digest(path)
               for path in sorted(destination.rglob('*')) if path.is_file()}
    manifest = {
        'gerado_em': datetime.now(timezone.utc).isoformat(),
        'origem': str(source), 'destino': str(destination),
        'candidatos': TARGETS,
        'identificadores': {slug: {key: sorted(values) for key, values in fields.items()}
                            for slug, fields in identities.items()},
        'escopo': 'Contas de titularidade dos candidatos; todos os turnos disponíveis, sem agregação.',
        'exclusoes': ['Contas gerais de órgãos partidários, não atribuíveis exclusivamente aos candidatos.',
                      'Recortes estaduais e BR: utilizados somente os consolidados BRASIL para evitar duplicação.'],
        'csv_saida': {'encoding': 'utf-8', 'delimitador': ';', 'colunas_e_valores': 'preservados'},
        'originais_inalterados': True, 'sha256_origens_antes': before,
        'sha256_origens_depois': after, 'sha256_saidas': outputs,
        'arquivos': results,
    }
    with (destination / 'manifesto.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(f'Concluído. Originais verificados por SHA-256. Saída: {destination}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origem', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--destino', type=Path,
                        default=DEFAULT_SOURCE.with_name('prestacao-de-contas-filtrada'))
    args = parser.parse_args()
    run(args.origem, args.destino)
