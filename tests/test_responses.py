import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import networkx as nx

from provenance.responses import TARGET, analyze_responses
from provenance.slice import backward_slice


def exchange(name, call_id, args, result):
    call = dict(type='function_call', name=name, call_id=call_id, arguments=json.dumps(args))
    return [
        dict(kind='response', body={'output': [call], 'status': 'completed'}),
        dict(kind='tool', name=name, call_id=call_id, arguments=args, result=result),
    ]


class ResponsesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.run_dir = self.root / 'run'

    def write(self, path, text):
        destination = self.run_dir / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding='utf-8')

    def write_log(self, path, rows):
        self.write(path, ''.join(json.dumps(row) + '\n' for row in rows))

    def prepare(self, *, passed=True, forwarded='requirements', child_script=None):
        # Synthetic protocol fixture. Both sessions reuse "read" as a call ID.
        script = 'x = 1\n' if passed else 'x = )\n'
        digest = hashlib.sha256(script.encode()).hexdigest()
        validation = dict(
            status='pass' if passed else 'unavailable',
            exit_code=0 if passed else 1, script_sha256=digest,
            stderr='' if passed else '  File "/work/validator.py", line 1\nSyntaxError: unmatched\n',
        )
        executor = [dict(kind='initial_prompt', content='Initial executor prompt')]
        executor += exchange('read_file', 'read', {'path': 'input/transactions.csv'},
                             {'content': 'a private fixture value'})
        executor += exchange('request_validator', 'delegate', {'handoff': 'requirements'},
                             {'validator_id': digest})
        executor += exchange('run_validator', 'check', {'validator_id': digest}, validation)
        child = [dict(kind='initial_prompt', content=f'Protocol\nHANDOFF:\n{forwarded}')]
        child += exchange('write_file', 'read', {'path': 'validator.py', 'content': script},
                          {'written': True})
        self.write_log('records/executor.jsonl', executor)
        self.write_log('records/verifier/events.jsonl', child)
        self.write('records/handoff.txt', 'requirements')
        self.write('records/validator.py', script)
        self.write('records/verifier/validator.py', script if child_script is None else child_script)
        self.write('records/validation.json', json.dumps(validation))
        self.write('records/checked-result.json', '{}')
        self.write('records/checked-input.csv', 'test,fixture\n')
        self.write('workspace/outputs/summary.json', '{}')
        self.write('records/evaluation.json', json.dumps(dict(
            oracle_correct=False, released=passed, wrong_released=passed,
            validation=validation, validation_status=validation['status'], checked_result_unchanged=True,
        )))

    def analyze(self):
        output = self.root / 'output'
        report = analyze_responses(self.run_dir, output)
        graph = nx.read_graphml(output / 'graph.graphml', force_multigraph=True)
        self.assertEqual(backward_slice(graph, TARGET), report['slices'][0])
        return report, graph

    def test_pass_links_both_sessions_without_exposing_raw_text(self):
        self.prepare()
        report, graph = self.analyze()
        self.assertTrue(report['decision']['wrong_released'])
        self.assertEqual(report['warnings'], [])
        links = {d['relation'] for _, _, d in graph.edges(data=True)}
        self.assertTrue({'HANDOFF_IN_PROMPT', 'USED_BY_CHECK', 'MATCHES_FINAL'}.issubset(links))
        evidence = report['slices'][0]
        self.assertIn('records/verifier/events.jsonl:line-3', {n['source_ref'] for n in evidence['observed']})
        possible = {n['source_ref'] for n in evidence['possible']}
        self.assertIn('records/executor.jsonl:line-3', possible)
        self.assertNotIn('a private fixture value', json.dumps(report))
        for source, target, edge in graph.edges(data=True):
            if edge['relation'] in ('RETURNED', 'PRECEDED', 'POSSIBLY_AVAILABLE'):
                self.assertEqual(source.split(':')[0], target.split(':')[0])

    def test_unavailable_reaches_syntax_error_and_withheld_decision(self):
        self.prepare(passed=False)
        report, graph = self.analyze()
        self.assertFalse(report['decision']['released'])
        self.assertEqual(report['validation_status'], 'unavailable')
        self.assertEqual(graph.nodes['validator:check']['diagnostic_ref'], 'records/validator.py:line-1')

    def test_missing_record_matches_leave_links_unconnected(self):
        self.prepare(forwarded='different requirements', child_script='# another file\n')
        self.write('workspace/outputs/summary.json', '{"changed":true}')
        report, graph = self.analyze()
        observed = {n['node'] for n in report['slices'][0]['observed']}
        self.assertNotIn('validator:handoff', graph)
        self.assertNotIn('result:final', graph)
        self.assertFalse(any(node.startswith('verifier:') for node in observed))
        self.assertEqual(len(report['warnings']), 3)

    def test_changed_script_is_not_linked_to_check(self):
        self.prepare()
        self.write('records/validator.py', '# changed saved script\n')
        report, graph = self.analyze()
        self.assertFalse(any(edge['relation'] == 'USED_BY_CHECK'
                             for _, _, edge in graph.out_edges('validator:script', data=True)))
        self.assertTrue(any('saved script hash' in warning for warning in report['warnings']))

    def test_output_cannot_overwrite_input_or_existing_report(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'outside the input'):
            analyze_responses(self.run_dir, self.run_dir / 'output')
        self.analyze()
        with self.assertRaises(FileExistsError):
            analyze_responses(self.run_dir, self.root / 'output')
