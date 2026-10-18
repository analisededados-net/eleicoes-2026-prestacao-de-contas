#!/usr/bin/env python3
"""Produz dados JSON para gráficos, sem modificar fontes ou publicar na plataforma."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from filtrar import DEFAULT_SOURCE, DIRECT, INDIRECT, TARGETS, digest, normalize

DEFAULT_INPUT = DEFAULT_SOURCE.with_name('prestacao-de-contas-filtrada')
DEFAULT_OUTPUT = DEFAULT_SOURCE.with_name('prestacao-de-contas-json')
FILES = {'receitas': DIRECT[0], 'contratadas': DIRECT[1], 'pagamentos': INDIRECT[0],
         'doadores_originarios': INDIRECT[1], 'extratos': DIRECT[4],
         'documentos_despesas': DIRECT[2], 'documentos_receitas': DIRECT[3]}
NULLS = {'', '#NULO', '#NE', '-1', '-3'}


def text(value):
    return None if value is None or value.strip() in NULLS else value.strip()


def money(value):
    if text(value) is None:
        raise ValueError('Valor monetário ausente')
    try:
        number = Decimal(value.replace('.', '').replace(',', '.')) * 100
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError(f'Valor monetário inválido: {value}')
        result = int(number)
        if abs(result) > 9007199254740991:
            raise ValueError('Valor excede precisão inteira do JavaScript')
        return result
    except InvalidOperation as error:
        raise ValueError(f'Valor monetário inválido: {value}') from error


def iso(value):
    return datetime.strptime(value, '%d/%m/%Y').date().isoformat() if text(value) else None


def party(row, kind):
    # Chave estável sem publicar CPF, CNPJ ou dados de contas bancárias nos JSONs.
    document = text(row.get('NR_CPF_CNPJ_' + kind))
    name = text(row.get('NM_' + kind)) or 'Não informado'
    identity = document or normalize(name)
    return {'chave': hashlib.sha256(identity.encode()).hexdigest(), 'nome': name}


def base(row, index):
    return {'linha_csv': index + 2, 'prestador_id': text(row.get('SQ_PRESTADOR_CONTAS')),
            'turno_declarado': text(row.get('ST_TURNO')),
            'tipo_prestacao': text(row.get('TP_PRESTACAO_CONTAS')),
            'data_prestacao': iso(row.get('DT_PRESTACAO_CONTAS'))}


def convert(row, index, kind):
    item = base(row, index)
    if kind == 'receitas':
        item.update(id=row['SQ_RECEITA'], data=iso(row['DT_RECEITA']),
                    valor_centavos=money(row['VR_RECEITA']), descricao=text(row['DS_RECEITA']),
                    fonte=text(row['DS_FONTE_RECEITA']), origem=text(row['DS_ORIGEM_RECEITA']),
                    natureza=text(row['DS_NATUREZA_RECEITA']), especie=text(row['DS_ESPECIE_RECEITA']),
                    doador=party(row, 'DOADOR'))
    elif kind == 'contratadas':
        item.update(id=row['SQ_DESPESA'], data=iso(row['DT_DESPESA']),
                    valor_centavos=money(row['VR_DESPESA_CONTRATADA']),
                    descricao=text(row['DS_DESPESA']), categoria=text(row['DS_ORIGEM_DESPESA']),
                    fornecedor=party(row, 'FORNECEDOR'))
    elif kind == 'pagamentos':
        item.update(id=row['SQ_PARCELAMENTO_DESPESA'], despesa_id=row['SQ_DESPESA'],
                    data=iso(row['DT_PAGTO_DESPESA']), valor_centavos=money(row['VR_PAGTO_DESPESA']),
                    descricao=text(row['DS_DESPESA']), categoria=text(row['DS_ORIGEM_DESPESA']),
                    fonte=text(row['DS_FONTE_DESPESA']))
    elif kind == 'doadores_originarios':
        item.update(receita_id=row['SQ_RECEITA'], data=iso(row['DT_RECEITA']),
                    valor_centavos=money(row['VR_RECEITA']), doador=party(row, 'DOADOR_ORIGINARIO'),
                    tipo_doador=text(row['TP_DOADOR_ORIGINARIO']))
    elif kind == 'extratos':
        item = {'linha_csv': index + 2, 'data': iso(row['DT_LANCAMENTO']),
                'valor_centavos': money(row['VR_LANCAMENTO']),
                'tipo': text(row['TP_LANCAMENTO']), 'operacao': text(row['NM_OPERACAO']),
                'fonte': text(row['NM_FONTE_RECURSO'])}
    else:
        # Atualmente vazios; falhar explicitamente se o leiaute passar a trazer dados.
        raise ValueError(f'Documentos presentes: implementar conversão específica de {kind}')
    return item


def aggregate(rows, key):
    groups = defaultdict(lambda: {'valor_centavos': 0, 'quantidade_lancamentos': 0})
    for row in rows:
        label = row.get(key) or 'Não informado'
        groups[label]['valor_centavos'] += row['valor_centavos']
        groups[label]['quantidade_lancamentos'] += 1
    total = sum(row['valor_centavos'] for row in rows)
    return [{'categoria': label, **value,
             'percentual': round(value['valor_centavos'] * 100 / total, 6) if total else None}
            for label, value in sorted(groups.items(), key=lambda pair: (-pair[1]['valor_centavos'], pair[0]))]


def ranking(rows, key):
    groups = {}
    for row in rows:
        person = row[key]
        group = groups.setdefault(person['chave'], {**person, 'valor_centavos': 0, 'quantidade_lancamentos': 0})
        group['valor_centavos'] += row['valor_centavos']
        group['quantidade_lancamentos'] += 1
    result = sorted(groups.values(), key=lambda row: (-row['valor_centavos'], row['chave']))
    total = sum(row['valor_centavos'] for row in rows)
    return {'quantidade_distinta': len(result),
            'participacao_top10_percentual': round(sum(r['valor_centavos'] for r in result[:10]) * 100 / total, 6) if total else None,
            'itens': result}


def timeline(datasets, weekly=False):
    buckets = defaultdict(Counter)
    undated = Counter()
    for name, rows in datasets.items():
        for row in rows:
            if row['data'] is None:
                undated[name] += row['valor_centavos']
                continue
            day = date.fromisoformat(row['data'])
            if weekly:
                day -= timedelta(days=day.weekday())
            buckets[day.isoformat()][name] += row['valor_centavos']
    points, cumulative = [], Counter()
    if buckets:
        day = date.fromisoformat(min(buckets))
        end = date.fromisoformat(max(buckets))
        while day <= end:
            key = day.isoformat()
            point = {'data': key}
            for name in datasets:
                amount = buckets.get(key, {}).get(name, 0)
                cumulative[name] += amount
                point[name + '_centavos'] = amount
                point[name + '_acumulado_centavos'] = cumulative[name]
            points.append(point)
            day += timedelta(days=7 if weekly else 1)
    return {'periodicidade': 'semana_iniciada_na_segunda' if weekly else 'dia',
            'sem_data_centavos': dict(undated), 'pontos': points}


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(content, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def build_candidate(source, destination, slug):
    datasets, quality = {}, {}
    snapshots = set()
    source_dates = set()
    for kind, relative in FILES.items():
        with (source / slug / relative).open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter=';'))
        counts = Counter(tuple(row.items()) for row in rows)
        quality[kind] = {'linhas': len(rows), 'repeticoes_exatas_preservadas': sum(n - 1 for n in counts.values())}
        if kind in ('receitas', 'contratadas', 'pagamentos', 'doadores_originarios'):
            snapshots.update((r['SQ_PRESTADOR_CONTAS'], r['ST_TURNO'],
                              normalize(r['TP_PRESTACAO_CONTAS']), r['DT_PRESTACAO_CONTAS']) for r in rows)
        source_dates.update(iso(r['DT_GERACAO']) for r in rows)
        datasets[kind] = [convert(row, index, kind) for index, row in enumerate(rows)]
    # Não escolher automaticamente entre prestações cumulativas/retificadoras.
    if len(snapshots) != 1:
        raise ValueError(f'{slug}: múltiplas versões de prestação; necessário definir seleção: {snapshots}')
    receipts = datasets['receitas']
    financial = [r for r in receipts if normalize(r['natureza'] or '') == 'FINANCEIRO']
    estimated = [r for r in receipts if normalize(r['natureza'] or '') == 'ESTIMAVEL']
    other = [r for r in receipts if r not in financial and r not in estimated]
    if other:
        raise ValueError(f'{slug}: natureza de receita desconhecida')
    total = lambda rows: sum(r['valor_centavos'] for r in rows)
    receipt_ids = {r['id'] for r in receipts}
    expense_ids = {r['id'] for r in datasets['contratadas']}
    quality['vinculos'] = {
        'doadores_originarios_sem_receita': sum(r['receita_id'] not in receipt_ids for r in datasets['doadores_originarios']),
        'pagamentos_sem_despesa': sum(r['despesa_id'] not in expense_ids for r in datasets['pagamentos'])}
    donor_ranking = ranking(receipts, 'doador')
    provider_ranking = ranking(datasets['contratadas'], 'fornecedor')
    overview = {
        'candidato': slug, 'nome': TARGETS[slug], 'datas_geracao_fontes': sorted(source_dates),
        'prestacao': {'prestador_id': next(iter(snapshots))[0], 'turno_declarado': next(iter(snapshots))[1],
                      'tipo': next(iter(snapshots))[2], 'data': iso(next(iter(snapshots))[3])},
        'indicadores': {'receitas_total_centavos': total(receipts),
                        'receitas_financeiras_centavos': total(financial),
                        'receitas_estimaveis_centavos': total(estimated),
                        'despesas_contratadas_centavos': total(datasets['contratadas']),
                        'despesas_pagas_centavos': total(datasets['pagamentos']),
                        'diferenca_contratado_pago_centavos': total(datasets['contratadas']) - total(datasets['pagamentos'])},
        'distribuicoes': {'receitas_por_fonte': aggregate(receipts, 'fonte'),
                          'receitas_por_origem': aggregate(receipts, 'origem'),
                          'receitas_por_natureza': aggregate(receipts, 'natureza'),
                          'receitas_financeiras_por_fonte': aggregate(financial, 'fonte'),
                          'despesas_por_categoria': aggregate(datasets['contratadas'], 'categoria'),
                          'pagamentos_por_categoria': aggregate(datasets['pagamentos'], 'categoria')},
        'qualidade': quality,
        'arquivos': {kind: f'{slug}/{kind}.json' for kind in datasets},
    }
    for kind, records in datasets.items():
        write(destination / slug / f'{kind}.json', {'candidato': slug, 'registros': records})
    series = {'receitas_financeiras': financial, 'receitas_estimaveis': estimated,
              'despesas_contratadas': datasets['contratadas'], 'pagamentos': datasets['pagamentos']}
    write(destination / slug / 'series.json', {'diaria': timeline(series), 'semanal': timeline(series, True)})
    write(destination / slug / 'rankings.json', {'doadores_imediatos': donor_ranking,
          'doadores_financeiros': ranking(financial, 'doador'), 'fornecedores_contratados': provider_ranking,
          'doadores_originarios': ranking(datasets['doadores_originarios'], 'doador')})
    write(destination / slug / 'resumo.json', overview)
    return overview, provider_ranking


def run(source, destination):
    source, destination = source.resolve(), destination.resolve()
    raw = DEFAULT_SOURCE.resolve()
    if any(destination == root or root in destination.parents for root in (source, raw)):
        raise ValueError('Destino deve ficar fora das fontes')
    manifest_path = source / 'manifesto.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    hashes = manifest['sha256_saidas']
    before = {relative: digest(source / relative) for relative in hashes}
    if before != hashes:
        raise ValueError('Fontes filtradas divergem do manifesto de integridade')
    destination.mkdir(parents=True, exist_ok=False)
    overviews, providers = {}, {}
    for slug in TARGETS:
        overviews[slug], providers[slug] = build_candidate(source, destination, slug)
    left = {r['chave']: r for r in providers['lula']['itens']}
    right = {r['chave']: r for r in providers['flavio-bolsonaro']['itens']}
    shared = [{'chave': key, 'nome': left[key]['nome'],
               'lula_centavos': left[key]['valor_centavos'],
               'flavio_bolsonaro_centavos': right[key]['valor_centavos']}
              for key in sorted(left.keys() & right.keys())]
    write(destination / 'comparativo.json', {'candidatos': list(overviews.values()), 'fornecedores_compartilhados': shared})
    after = {relative: digest(source / relative) for relative in hashes}
    if after != before:
        raise RuntimeError('Fontes alteradas durante o processamento')
    output_hashes = {str(p.relative_to(destination)): digest(p) for p in sorted(destination.rglob('*.json'))}
    metadata = {
        'schema_version': 1, 'gerado_em': datetime.now(timezone.utc).isoformat(),
        'unidade_monetaria': 'centavos de BRL, inteiros', 'datas': 'ISO 8601, YYYY-MM-DD',
        'origem': str(source), 'fontes_inalteradas': True, 'sha256_fontes': before,
        'sha256_arquivos': output_hashes,
        'candidatos': [{'id': slug, 'nome': name, 'resumo': f'{slug}/resumo.json',
                        'series': f'{slug}/series.json', 'rankings': f'{slug}/rankings.json'} for slug, name in TARGETS.items()],
        'comparativo': 'comparativo.json',
        'avisos': [
            'Totais declarados provisórios; não representam auditoria ou aprovação das contas.',
            'Itens com o mesmo identificador e linhas idênticas são preservados; ver qualidade nos resumos.',
            'Receitas estimáveis não são dinheiro em caixa; não usar receita total como saldo bancário.',
            'Diferença entre contratado e pago não é automaticamente dívida ou saldo.',
            'Doadores originários detalham receitas: não somar seus valores às receitas principais.',
            'Extratos não integram totais de receitas ou despesas e não foram conciliados.',
            'Turno declarado identifica a prestação, não necessariamente a data do gasto ou receita.',
            'Não publicados CPF/CNPJ, contas, agências, contrapartes bancárias ou documentos nos JSONs.',
            'Chaves hash são pseudônimos de agrupamento, não garantia de anonimato.',
            'Dados pessoais e bancários continuam disponíveis apenas nas fontes locais existentes.',
        ],
    }
    write(destination / 'index.json', metadata)
    print(f'JSONs gerados e fontes verificadas: {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origem', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--destino', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.origem, args.destino)
