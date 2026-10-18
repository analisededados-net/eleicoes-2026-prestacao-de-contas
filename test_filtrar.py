import csv
import json
from pathlib import Path
import tempfile
import unittest

from filtrar import CNPJ, DIRECT, INDIRECT, TARGETS, digest, run


class FilterTests(unittest.TestCase):
    def fixture(self, root):
        fields = ['AA_ELEICAO', 'NM_CANDIDATO', 'SQ_CANDIDATO', 'SQ_PRESTADOR_CONTAS',
                  'NR_CNPJ_PRESTADOR_CONTA', 'ST_TURNO', 'DS_RECEITA', 'NM_DOADOR']
        rows = [
            ['2026', TARGETS['lula'], '001', '101', '00000000000001', '1', 'ação; teste', 'Outro'],
            ['2026', 'FLÁVIO NANTES BOLSONARO', '002', '102', '00000000000002', '2', 'Teste', 'Outro'],
            ['2026', 'CARLOS EDUARDO DE OLIVEIRA LULA', '003', '103', '00000000000003', '1', '', TARGETS['lula']],
        ]
        for relative in DIRECT + INDIRECT:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='latin1', newline='') as stream:
                writer = csv.writer(stream, delimiter=';')
                if relative in INDIRECT:
                    writer.writerow(['AA_ELEICAO', 'SQ_PRESTADOR_CONTAS', 'ST_TURNO'])
                    writer.writerows([[row[0], row[3], row[5]] for row in rows])
                else:
                    writer.writerow(fields)
                    writer.writerows(rows)
        path = root / CNPJ
        path.parent.mkdir(parents=True, exist_ok=True)
        records = ['1' + ' ' * 199]
        for i, name in enumerate(TARGETS.values(), 1):
            records.append('202' + str(i).zfill(14) + name.ljust(150) + ' ' * 33)
        records.append('9000000002' + ' ' * 190)
        path.write_text('\n'.join(records), encoding='latin1')

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as folder:
            source, destination = Path(folder) / 'raw', Path(folder) / 'filtered'
            self.fixture(source)
            before = {str(p): digest(p) for p in source.rglob('*') if p.is_file()}
            run(source, destination)
            manifest = json.loads((destination / 'manifesto.json').read_text())
            self.assertTrue(manifest['originais_inalterados'])
            self.assertEqual(before, {str(p): digest(p) for p in source.rglob('*') if p.is_file()})
            for item in manifest['arquivos']:
                self.assertEqual(item['selecionados'], {'lula': 1, 'flavio-bolsonaro': 1})
            for slug in TARGETS:
                for relative in DIRECT + INDIRECT:
                    with (destination / slug / relative).open(encoding='utf-8', newline='') as stream:
                        self.assertEqual(len(list(csv.DictReader(stream, delimiter=';'))), 1)
                lines = (destination / slug / CNPJ).read_text(encoding='latin1').splitlines()
                self.assertEqual(len(lines), 3)
                self.assertTrue(all(len(line) == 200 for line in lines))
                self.assertTrue(lines[-1].startswith('9000000001'))
            with (destination / 'lula' / DIRECT[0]).open(encoding='utf-8', newline='') as stream:
                row = next(csv.DictReader(stream, delimiter=';'))
                self.assertEqual(row['SQ_CANDIDATO'], '001')
                self.assertEqual(row['DS_RECEITA'], 'ação; teste')
            with self.assertRaises(FileExistsError):
                run(source, destination)

    def test_reject_output_inside_source(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as folder:
            source = Path(folder)
            with self.assertRaises(ValueError):
                run(source, source / 'filtered')


if __name__ == '__main__':
    unittest.main()
