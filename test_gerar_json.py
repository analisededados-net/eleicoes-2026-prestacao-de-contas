import csv
import json
from pathlib import Path
import tempfile
import unittest

from filtrar import digest
from gerar_json import FILES, TARGETS, aggregate, money, run, timeline


class JsonTests(unittest.TestCase):
    def fixture(self, source):
        row = {
            'SQ_PRESTADOR_CONTAS': '001', 'ST_TURNO': '2',
            'TP_PRESTACAO_CONTAS': 'Relatório Financeiro', 'DT_PRESTACAO_CONTAS': '16/10/2026',
            'DT_GERACAO': '18/10/2026', 'SQ_RECEITA': '002', 'DT_RECEITA': '01/10/2026',
            'VR_RECEITA': '10,01', 'DS_RECEITA': 'Doação', 'DS_FONTE_RECEITA': 'OUTROS RECURSOS',
            'DS_ORIGEM_RECEITA': 'Pessoas físicas', 'DS_NATUREZA_RECEITA': 'FINANCEIRO',
            'DS_ESPECIE_RECEITA': 'Transferência', 'NR_CPF_CNPJ_DOADOR': '01234567890',
            'NM_DOADOR': 'Pessoa', 'SQ_DESPESA': '003', 'DT_DESPESA': '02/10/2026',
            'VR_DESPESA_CONTRATADA': '5,10', 'DS_DESPESA': 'Serviço',
            'DS_ORIGEM_DESPESA': 'Serviços', 'NR_CPF_CNPJ_FORNECEDOR': '00000000000001',
            'NM_FORNECEDOR': 'Fornecedor', 'SQ_PARCELAMENTO_DESPESA': '004',
            'DT_PAGTO_DESPESA': '03/10/2026', 'VR_PAGTO_DESPESA': '2,00',
            'DS_FONTE_DESPESA': 'Outros', 'NR_CPF_CNPJ_DOADOR_ORIGINARIO': '01234567890',
            'NM_DOADOR_ORIGINARIO': 'Pessoa', 'TP_DOADOR_ORIGINARIO': 'F',
            'DT_LANCAMENTO': '03/10/2026', 'VR_LANCAMENTO': '2,00',
            'TP_LANCAMENTO': 'D', 'NM_OPERACAO': 'Débito', 'NM_FONTE_RECURSO': 'Outros',
        }
        hashes = {}
        for slug in TARGETS:
            for kind, relative in FILES.items():
                path = source / slug / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(row), delimiter=';')
                    writer.writeheader()
                    if not kind.startswith('documentos'):
                        writer.writerow(row)
                        if kind == 'contratadas':
                            writer.writerow(row)  # Repetição ambígua não pode desaparecer.
                hashes[str(path.relative_to(source))] = digest(path)
        (source / 'manifesto.json').write_text(json.dumps({'sha256_saidas': hashes}))

    def test_money(self):
        self.assertEqual(money('1.234,56'), 123456)
        self.assertEqual(money('-0,01'), -1)
        for value in ('#NULO', '1,234', 'NaN', 'Infinity', 'abc'):
            with self.assertRaises(ValueError):
                money(value)

    def test_series_and_distributions(self):
        rows = [{'data': '2026-10-01', 'valor_centavos': 101, 'fonte': 'A'},
                {'data': '2026-10-03', 'valor_centavos': 202, 'fonte': 'B'}]
        points = timeline({'receitas': rows})['pontos']
        self.assertEqual(len(points), 3)
        self.assertEqual(points[1]['receitas_centavos'], 0)
        self.assertEqual(points[-1]['receitas_acumulado_centavos'], 303)
        weekly = timeline({'receitas': rows}, weekly=True)['pontos']
        self.assertEqual(weekly[0]['data'], '2026-09-28')
        self.assertEqual(weekly[0]['receitas_centavos'], 303)
        self.assertEqual(sum(r['valor_centavos'] for r in aggregate(rows, 'fonte')), 303)

    def test_end_to_end_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as folder:
            source, destination = Path(folder) / 'source', Path(folder) / 'output'
            self.fixture(source)
            run(source, destination)
            summary = json.loads((destination / 'lula/resumo.json').read_text())
            self.assertEqual(summary['indicadores']['receitas_total_centavos'], 1001)
            self.assertEqual(summary['indicadores']['despesas_contratadas_centavos'], 1020)
            self.assertEqual(summary['qualidade']['contratadas']['repeticoes_exatas_preservadas'], 1)
            self.assertEqual(summary['qualidade']['vinculos']['doadores_originarios_sem_receita'], 0)
            metadata = json.loads((destination / 'index.json').read_text())
            for relative, expected in metadata['sha256_arquivos'].items():
                self.assertEqual(digest(destination / relative), expected)
                content = (destination / relative).read_text()
                self.assertNotIn('01234567890', content)
            with self.assertRaises(FileExistsError):
                run(source, destination)

    def test_tampered_input_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as folder:
            source, destination = Path(folder) / 'source', Path(folder) / 'output'
            self.fixture(source)
            (source / 'lula' / FILES['receitas']).write_text('alterado')
            with self.assertRaises(ValueError):
                run(source, destination)
            self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
