"""Tests de contrat et d'orchestration, pas des réestimations statistiques.
Toutes les substitutions de moteurs sont locales aux tests et temporaires.
"""
from __future__ import annotations
import ast
from contextlib import contextmanager
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

from reproducibility import replication_complete as r

class Contracts(unittest.TestCase):
    def test_whole_plan(self):
        p=r.contract_plan()
        self.assertEqual((p['raw_archives'],p['krt_pairs'],p['r_ei_pairs'],p['nls_delivered_pairs'],p['nls_covariates'],p['expected_result_files']), (31,240,240,292,960,610))
    def test_all_original_scientific_files_unchanged(self):
        original=r.read_json(r.CONTRACT/'original_package_files.json')['files']
        self.assertEqual(r.check_original_integrity()['unchanged_original_files'],
                         sum(row['path'] not in r.MODIFIED_ORIGINALS and
                             not any(row['path'].startswith(prefix)
                                     for prefix in r.ALLOWED_RUNTIME_REPLACEMENT_PREFIXES)
                             for row in original))
    def test_only_cli_runtime_is_an_allowed_r_replacement(self):
        self.assertEqual(r.ALLOWED_RUNTIME_REPLACEMENT_PREFIXES,
                         ('.cache/R/library/cli/',))
    def test_reject_modified_seed(self):
        read=r.read_json
        def changed(p):
            x=read(p)
            if p.name=='krt_replay_240.json': x['entries'][0]['arguments']['random_seed'] += 1
            return x
        with patch.object(r,'read_json',side_effect=changed), self.assertRaises(r.ReplicationError): r.contract_plan()
    def test_reject_modified_hash_proof(self):
        read=r.read_json
        def changed(p):
            x=read(p)
            if p.name=='krt_replay_240.json': x['entries'][0]['historical_hash_payload']['parameters']['draws'] += 1
            return x
        with patch.object(r,'read_json',side_effect=changed), self.assertRaises(r.ReplicationError): r.contract_plan()
    def test_reject_duplicate_pair(self):
        read=r.read_json
        def changed(p):
            x=read(p)
            if p.name=='krt_replay_240.json': x['entries'][1]=copy.deepcopy(x['entries'][0])
            return x
        with patch.object(r,'read_json',side_effect=changed), self.assertRaises(r.ReplicationError): r.contract_plan()
    def test_code_compiles_without_executing(self):
        files=list((r.ROOT/'code_longitudinal').glob('*.py'))+list((r.ROOT/'reproducibility').glob('*.py'))
        self.assertGreater(len(files),80)
        for f in files: compile(f.read_text(encoding='utf-8-sig'),str(f),'exec')
    def test_no_reference_capture_or_restore_pdf_in_new_path(self):
        text=Path(r.__file__).read_text()
        self.assertNotIn('module("restore_report',text)
        self.assertNotIn('module("finalize_professor_delivery',text)
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('"capture"',launcher)
        self.assertNotIn('"finalize-longitudinal"',launcher)
    def test_launcher_requires_exact_bootstrap_python_before_creating_venv(self):
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('Get-Command py.exe',launcher)
        self.assertIn('Test-PythonRuntimeStatus $bootstrapStatus',launcher)
        self.assertIn('$Status.version -eq "3.12.10"',launcher)
        self.assertIn('$Status.system -eq "Windows"',launcher)
        self.assertIn('$Status.pointer_bits -eq 64',launcher)
        self.assertIn('$Status.pip_usable',launcher)
        self.assertIn('$Status.is_venv',launcher)
    def test_raw_downloader_is_explicit_resumable_and_fail_closed(self):
        downloader=(r.ROOT/'TELECHARGER_DONNEES_BRUTES.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('raw_sources_31.json',downloader)
        self.assertIn('$sources.Count -ne 31',downloader)
        self.assertIn("[string]$DossierDestination = ''",downloader)
        self.assertIn("$DossierDestination = Join-Path $PSScriptRoot 'DONNEES_BRUTES'",downloader)
        self.assertIn('Get-FileHash -LiteralPath $Path -Algorithm SHA256',downloader)
        self.assertIn('$downloadPath = Join-Path $destination ([string]$source.download_name)',downloader)
        self.assertIn('if (Test-SourceFile -Path $candidatePath -Source $source)',downloader)
        self.assertIn('$authenticatedPath = $candidatePath',downloader)
        self.assertNotIn('$authenticatedPath = $candidatePath\n            break',downloader)
        self.assertIn('Copie supplementaire ignoree car non conforme',downloader)
        self.assertIn('$VerifierSeulement',downloader)
        self.assertIn('Invoke-WebRequest -Uri ([string]$source.source_url)',downloader)
        self.assertIn('$totalBytes -ne 1620387967',downloader)
        self.assertNotIn('longitudinal_2000_results.zip',downloader)
    def test_launcher_recovers_an_interrupted_local_venv_creation(self):
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('.creation-in-progress',launcher)
        self.assertIn('Environnement local incomplet detecte',launcher)
        self.assertIn('Remove-Item -LiteralPath $projectEnvironment -Recurse -Force',launcher)
        self.assertLess(launcher.index('Test-PythonRuntimeStatus $createdStatus'),
                        launcher.index('Remove-Item -LiteralPath $creationMarker -Force'))
    def test_launcher_preserves_bound_arguments_for_failure_resume(self):
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('$scriptBoundParameters[$item.Key] = $item.Value',launcher)
        self.assertIn('$resumeCommand = New-ResumeCommand $scriptBoundParameters',launcher)
        self.assertIn('$env:LONGITUDINAL_RESUME_COMMAND = $resumeCommand',launcher)
    def test_required_extra_sources(self):
        rows=r.read_json(r.CONTRACT/'raw_sources_31.json')['raw_sources']
        names={x['name'] for x in rows}
        self.assertTrue({'socio_agl_csv.zip','socio_rev_csv.zip','socio_cap_csv.zip','socio_nat_csv.zip'}<=names)
        aliases=[value for row in rows for value in (row['name'],row['download_name'])]
        self.assertEqual(len(aliases),len({value.casefold() for value in aliases}))
        self.assertTrue(all(value and '/' not in value and '\\' not in value and value.lower().endswith('.zip')
                            for value in aliases))
    def test_every_critical_r_package_has_an_explicit_version(self):
        lock=r.read_json(r.ROOT/'reproducibility/r-packages.lock.json')
        critical=r.read_json(r.CONTRACT/'critical_r_versions.json')['versions']
        self.assertEqual(set(lock['critical_packages']),set(critical))
        self.assertEqual(critical['MASS'],'7.3-65')
        recorded={x['package']:x['version'] for x in lock['packages']}
        for package in set(lock['critical_packages'])-{'MASS'}:
            self.assertEqual(critical[package],recorded[package])
    def test_covariate_and_density_stages_present(self):
        self.assertIn('covariates960',r.STAGES)
        self.assertLess(r.STAGES.index('assets'),r.STAGES.index('density480'))
        self.assertLess(r.STAGES.index('density480'),r.STAGES.index('report'))
    def test_canonical_before_full_consolidation(self):
        self.assertLess(r.STAGES.index('canonical52'),r.STAGES.index('consolidate240'))
        self.assertLess(r.STAGES.index('nls270'),r.STAGES.index('canonical52'))
    def test_preflight_initializes_jax_stack_before_pymc_and_pyei(self):
        self.assertLess(r.PREFLIGHT_IMPORTS.index('jax'),r.PREFLIGHT_IMPORTS.index('numpyro'))
        self.assertLess(r.PREFLIGHT_IMPORTS.index('numpyro'),r.PREFLIGHT_IMPORTS.index('pymc'))
        self.assertLess(r.PREFLIGHT_IMPORTS.index('numpyro'),r.PREFLIGHT_IMPORTS.index('pyei'))
    def test_prepare_has_hard_gate_before_first_estimator(self):
        self.assertLess(r.STAGES.index('prepare'),r.STAGES.index('nls270'))
        source=Path(r.__file__).read_text(encoding='utf-8-sig')
        prepare=source.index('elif stage == "prepare"')
        nls=source.index('elif stage == "nls270"')
        self.assertIn('validate_prepared_inputs(records',source[prepare:nls])
    def test_launcher_exposes_resource_threshold_controls(self):
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        for option in ('$MinimumFreeDiskGB','$MinimumAvailableMemoryGB','$ExigerRessourcesRecommandees'):
            self.assertIn(option,launcher)
    def test_public_guide_uses_generic_archive_name_and_keeps_strict_full_run(self):
        guide=(r.ROOT/'COMMENCER_ICI.md').read_text(encoding='utf-8-sig')
        self.assertIn('longitudinal_2000_reproduction_complete_PORTABLE_CERTIFICATION.zip',guide)
        self.assertNotIn('longitudinal_2000_reproduction_complete_v2_6_PORTABLE_CERTIFICATION.zip',guide)
        self.assertNotIn('révision technique interne 2.6',guide)
        self.assertIn('https://www.python.org/downloads/release/python-31210/',guide)
        self.assertIn('https://cran.r-project.org/bin/windows/base/old/4.6.0/',guide)
        self.assertIn('https://www.microsoft.com/edge/download',guide)
        full_command='powershell -ExecutionPolicy Bypass -File .\\REPRODUIRE_TOUT.ps1 `\n  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5'
        self.assertIn(full_command,guide)
    def test_launcher_prefers_exact_r_460_before_path(self):
        launcher=(r.ROOT/'REPRODUIRE_TOUT.ps1').read_text(encoding='utf-8-sig')
        exact=launcher.index("$rRoot = Join-Path $env:ProgramFiles \"R\"")
        path_fallback=launcher.index('Get-Command Rscript.exe')
        self.assertLess(exact,path_fallback)
        self.assertIn("-match 'R-4\\.6\\.0'",launcher[exact:path_fallback])
    def test_final_verification_requires_exact_arrow_schema_and_bounded_pdf(self):
        source=Path(r.__file__).read_text(encoding='utf-8-sig')
        self.assertEqual(r.PDF_RENDER_TIMEOUT_SECONDS,15*60)
        self.assertIn('meta.schema_arrow.names == contract["columns"]',source)
        self.assertIn('str(meta.schema_arrow) == contract["schema"]',source)

class RawSources(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='sources avec espaces ')
        self.root=Path(self.temp.name)
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('fixture.csv',b'example test bytes, NOT project data')
        self.data=payload.getvalue()
        self.source=[dict(name='canonical.zip',download_name='Official.zip',bytes=len(self.data),required_sha256=hashlib.sha256(self.data).hexdigest())]
    def tearDown(self): self.temp.cleanup()
    def test_missing(self):
        with self.assertRaisesRegex(r.ReplicationError,'MANQUANT'): r.resolve_raw(self.root,sources=self.source)
    def test_wrong_hash(self):
        (self.root/'canonical.zip').write_bytes(self.data[:-1]+b'x')
        with self.assertRaisesRegex(r.ReplicationError,'SHA256 DIFFERENT'): r.resolve_raw(self.root,sources=self.source)
    def test_nested_official_name_is_accepted_and_normalized(self):
        p=self.root/'sous dossier';p.mkdir();(p/'Official.zip').write_bytes(self.data)
        result=r.resolve_raw(self.root,sources=self.source,runtime=self.root/'runtime')
        self.assertEqual(result['count'],1)
        self.assertEqual((Path(result['raw_dir'])/'canonical.zip').read_bytes(),self.data)
    def test_direct_names_do_not_copy_data(self):
        (self.root/'canonical.zip').write_bytes(self.data)
        x=r.resolve_raw(self.root,sources=self.source,runtime=self.root/'runtime')
        self.assertEqual(Path(x['raw_dir']),self.root)
        self.assertFalse((self.root/'runtime').exists())
    def test_existing_bad_normalization_rejected(self):
        (self.root/'Official.zip').write_bytes(self.data)
        target=self.root/'runtime/raw_archives';target.mkdir(parents=True)
        (target/'canonical.zip').write_bytes(b'corruption')
        with self.assertRaisesRegex(r.ReplicationError,'normalisee differente'):
            r.resolve_raw(self.root,sources=self.source,runtime=self.root/'runtime')
    def test_valid_duplicate_found_even_if_other_copy_bad(self):
        (self.root/'canonical.zip').write_bytes(b'bad')
        (self.root/'Official.zip').write_bytes(self.data)
        self.assertEqual(r.resolve_raw(self.root,sources=self.source,runtime=self.root/'run')['count'],1)
    def test_crc_corruption_is_rejected_even_when_outer_hash_matches(self):
        corrupted=bytearray(self.data)
        location=self.data.index(b'example test bytes')
        corrupted[location] ^= 0x01
        damaged=bytes(corrupted)
        source=[dict(name='canonical.zip',download_name='Official.zip',bytes=len(damaged),required_sha256=hashlib.sha256(damaged).hexdigest())]
        (self.root/'canonical.zip').write_bytes(damaged)
        with self.assertRaisesRegex(r.ReplicationError,'CRC/lecture ZIP'):
            r.resolve_raw(self.root,sources=source)
    def test_duplicate_logical_zip_path_is_rejected(self):
        payload=io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(payload,'w') as archive:
                archive.writestr('same.csv',b'a')
                archive.writestr('SAME.csv',b'b')
        data=payload.getvalue()
        source=[dict(name='canonical.zip',download_name='Official.zip',bytes=len(data),required_sha256=hashlib.sha256(data).hexdigest())]
        (self.root/'canonical.zip').write_bytes(data)
        with self.assertRaisesRegex(r.ReplicationError,'dupliques'):
            r.resolve_raw(self.root,sources=source)

class ResourcesAndWrites(unittest.TestCase):
    def test_resource_recommendations_warn_but_transient_low_ram_does_not_block(self):
        disk=SimpleNamespace(total=100*r.GIB,used=80*r.GIB,free=20*r.GIB)
        memory=SimpleNamespace(total=int(15.5*r.GIB),available=int(2.4*r.GIB),percent=84.5)
        with patch.object(r.shutil,'disk_usage',return_value=disk), \
             patch('psutil.virtual_memory',return_value=memory), \
             patch.dict(os.environ,{
                 'LONGITUDINAL_ENFORCE_RESOURCE_RECOMMENDATIONS':'0',
                 'LONGITUDINAL_MIN_FREE_DISK_GB':'',
                 'LONGITUDINAL_MIN_AVAILABLE_MEMORY_GB':'',
                 'LONGITUDINAL_MIN_TOTAL_MEMORY_GB':'',
             },clear=False):
            result=r.validate_runtime_resources(Path.cwd())
        self.assertEqual(result['status'],'pass_with_warnings')
        self.assertTrue(any('garde R' in item for item in result['warnings']))
    def test_explicit_resource_threshold_is_blocking(self):
        disk=SimpleNamespace(total=100*r.GIB,used=80*r.GIB,free=20*r.GIB)
        memory=SimpleNamespace(total=int(15.5*r.GIB),available=int(2.4*r.GIB),percent=84.5)
        with patch.object(r.shutil,'disk_usage',return_value=disk), \
             patch('psutil.virtual_memory',return_value=memory), \
             patch.dict(os.environ,{'LONGITUDINAL_MIN_FREE_DISK_GB':'30'},clear=False), \
             self.assertRaisesRegex(r.ReplicationError,'Espace disque libre insuffisant'):
            r.validate_runtime_resources(Path.cwd())
    def test_real_write_and_atomic_replace_probe(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); state=root/'.runtime'/'replication_v2'
            result=r.validate_writable_directories(root,state)
            self.assertEqual(result['status'],'pass')
            self.assertEqual(len(result['directories_checked']),6)
            self.assertFalse(list(root.rglob('.preflight_write_probe.*')))

class PackageAndRIntegrity(unittest.TestCase):
    def test_package_change_receipt_authenticates_modified_files(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); contract=root/'reproducibility'/'contract_v2';contract.mkdir(parents=True)
            shipped=root/'launcher.ps1';shipped.write_text('exact',encoding='utf-8')
            receipt=contract/'CHANGEMENTS_FICHIERS.csv'
            receipt.write_text('path,status,original_sha256,new_sha256\nlauncher.ps1,modified,,'+r.digest(shipped)+'\n',encoding='utf-8')
            self.assertEqual(r.check_package_manifest_integrity(root)['files_verified'],1)
            shipped.write_text('changed',encoding='utf-8')
            with self.assertRaisesRegex(r.ReplicationError,'modifies/manquants'):
                r.check_package_manifest_integrity(root)
    def test_every_bundled_r_file_is_authenticated(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); library=root/'.cache'/'R'/'library';library.mkdir(parents=True)
            package=library/'fixture';package.mkdir();(package/'DESCRIPTION').write_text('Package: fixture\nVersion: 1.0\n')
            fingerprint=r.tree_fingerprint(package)
            manifest={
                'package_count':1,'file_count':fingerprint['files'],'bytes':fingerprint['bytes'],
                'r_version':'4.6.0','platform':'x86_64-w64-mingw32',
                'packages':[{'package':'fixture','version':'1.0',**fingerprint}],
            }
            manifest_path=root/'reproducibility'/'r-runtime-library-manifest.json';manifest_path.parent.mkdir()
            manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
            self.assertEqual(r.validate_r_runtime_library(root)['packages'],1)
            (package/'DESCRIPTION').write_text('Package: fixture\nVersion: 2.0\n')
            with self.assertRaisesRegex(r.ReplicationError,'modifie/corrompu'):
                r.validate_r_runtime_library(root)

class Failures(unittest.TestCase):
    def test_nls_failure_not_success(self):
        with self.assertRaises(r.ReplicationError): r.validate_result_count(dict(success_or_resumed=269,failed=1),270,'success_or_resumed','failed')
    def test_r_failure_not_success(self):
        with self.assertRaises(r.ReplicationError): r.validate_result_count(dict(pairs_successful=239,pairs_failed=1),240,'pairs_successful','pairs_failed')
    def test_no_error_count_does_not_hide_incomplete_scope(self):
        with self.assertRaises(r.ReplicationError): r.validate_result_count(dict(pairs_successful=52),240,'pairs_successful','pairs_failed')
    def test_inventory_missing_file_detected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); (p/'one.csv').write_text('x')
            self.assertEqual(r.inventory_missing(p,[dict(path='one.csv'),dict(path='two.csv')]),['two.csv'])
    def test_only_generated_manifest_may_be_pending(self):
        with tempfile.TemporaryDirectory() as t:
            rows=[dict(path='data.csv'),dict(path='06_DOCUMENTATION/DELIVERY_MANIFEST.json')]
            self.assertEqual(r.inventory_missing(Path(t),rows,True),['data.csv'])
    def test_external_failure_propagates(self):
        with patch.object(r.subprocess,'run',side_effect=subprocess.CalledProcessError(9,['test'])):
            with self.assertRaises(subprocess.CalledProcessError):r.external(['test'])

class BrowserPDF(unittest.TestCase):
    def test_standalone_preflight_creates_fresh_nested_state_before_pdf_probe(self):
        pins = {}
        for line in (r.ROOT/'reproducibility/requirements-python312.lock.txt').read_text().splitlines() + ['mistune==3.3.4']:
            if '==' in line and not line.startswith('#'):
                name, version = line.strip().split('==', 1)
                pins[name] = version
        with tempfile.TemporaryDirectory(prefix='fresh preflight ') as t:
            root=Path(t); state=root/'never created'/'runtime'/'replication_v2'
            executable=root/'fixture.exe'; executable.touch()
            self.assertFalse(state.parent.exists())
            checked=[]
            def pdf_probe(html, pdf, browser):
                self.assertTrue(state.is_dir())
                self.assertEqual(html.parent.parent, state)
                self.assertTrue(html.is_file())
                pdf.write_bytes(b'%PDF-1.4\nfixture\n%%EOF\n')
                checked.append(pdf)
            with patch.object(r,'STATE_DIR',state), \
                 patch.object(r,'contract_plan',return_value={}), \
                 patch.object(r,'check_original_integrity',return_value={}), \
                 patch.object(r,'check_package_manifest_integrity',return_value={}), \
                 patch.object(r,'resolve_raw',return_value={'raw_dir':str(root/'raw')}), \
                 patch.object(r.platform,'python_version',return_value='3.12.10'), \
                 patch.object(r.importlib.metadata,'version',side_effect=pins.__getitem__), \
                 patch.object(r,'PREFLIGHT_IMPORTS',()), \
                 patch.object(r,'validate_runtime_resources',return_value={}), \
                 patch.object(r,'validate_writable_directories',return_value={}), \
                 patch.object(r,'validate_r_runtime_library',return_value={}), \
                 patch.object(r,'write_preflight_receipts',return_value={}), \
                 patch('code_longitudinal.run_r_ei_all_2x2._reference_seeds',return_value=dict.fromkeys(range(240))), \
                 patch.object(r,'configure'), patch.object(r,'external'), \
                 patch.object(r,'render_pdf',side_effect=pdf_probe):
                result=r.preflight(root/'raw',str(executable),str(executable))
            self.assertEqual(result['status'],'preflight_pass_no_estimations')
            self.assertEqual(len(checked),1)
            self.assertTrue(state.is_dir())
            self.assertFalse(checked[0].parent.exists())

    def test_render_pdf_waits_for_async_browser_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); state=root/'state'
            html=root/'input.html'; html.write_text('<p>test</p>',encoding='utf-8')
            pdf=root/'output.pdf'
            def delayed_write(*args,**kwargs):
                def write_pdf():
                    time.sleep(0.1)
                    pdf.write_bytes(b'%PDF-1.4\n'+b'x'*128+b'\n%%EOF\n')
                threading.Thread(target=write_pdf,daemon=True).start()
            with patch.object(r,'STATE_DIR',state), patch.object(r,'external',side_effect=delayed_write):
                r.render_pdf(html,pdf,'browser.exe')
            self.assertGreater(pdf.stat().st_size,100)
            self.assertTrue(state.is_dir())

class Dispatch(unittest.TestCase):
    class FakeOwnedProcess:
        _next_pid=700000
        def __init__(self,returncode=0):
            type(self)._next_pid+=1
            self.pid=type(self)._next_pid
            self.returncode=returncode
        def wait(self,timeout=None): return self.returncode
        def poll(self): return self.returncode
        def kill(self): self.returncode=-9

    def test_duplicate_launcher_is_rejected_and_lock_released(self):
        with tempfile.TemporaryDirectory() as t, patch.object(r,'ROOT',Path(t)):
            with r.exclusive_pipeline():
                with self.assertRaisesRegex(r.ReplicationError,'deja active'):
                    with r.exclusive_pipeline():
                        self.fail('duplicate launcher entered')
            with r.exclusive_pipeline():
                pass

    def test_all_240_actual_dispatch_arguments(self):
        # Actual worker and original registry, with only the costly sampling call replaced.
        plan=r.read_json(r.CONTRACT/'krt_replay_240.json')['entries']; seen=[]
        def fake(e,s,model,**kw):
            seen.append((e.election_id,s.scenario_id,model,kw));return {'status':'success'}
        mapping={x['reference_run_id']:(Path('unused'),{'run_id':'simulation_only'}) for x in plan}
        with tempfile.TemporaryDirectory() as t, patch.object(r,'STATE_DIR',Path(t)), \
             patch('code_longitudinal.run_2x2_batch.run_2x2',side_effect=fake), \
             patch.object(r,'_validated_krt_run',return_value=(Path('unused'),{'run_id':'simulation_only'})), \
             patch.object(r,'krt_manifest_map',return_value=mapping), patch.object(r,'activate_runtime_panel_hash'):
            r.worker('krt240')
        self.assertEqual(len(seen),240)
        self.assertEqual({(x[0],x[1]) for x in seen},r.expected_pairs())
        for dispatched,expected in zip(seen,plan):
            for key,val in expected['arguments'].items():self.assertEqual(dispatched[3][key],val)
            self.assertEqual(dispatched[3]['sample_size'],2000)
            self.assertEqual(dispatched[3]['run_metadata']['reference_run_id'],expected['reference_run_id'])
    def test_krt_failure_preserves_other_independent_dispatches_but_blocks_consolidation(self):
        calls=[]
        def fake(*a,**kw):
            calls.append(kw)
            return {'status':'failed'} if len(calls)==3 else {'status':'success'}
        with tempfile.TemporaryDirectory() as t, patch.object(r,'STATE_DIR',Path(t)), \
             patch('code_longitudinal.run_2x2_batch.run_2x2',side_effect=fake), \
             patch.object(r,'_validated_krt_run',return_value=(Path('unused'),{'run_id':'simulation_only'})), \
             patch.object(r,'activate_runtime_panel_hash'), \
             patch.object(r,'krt_manifest_map') as consolidation:
            with self.assertRaises(r.BatchEstimationError) as failed:
                r.worker('krt240')
            self.assertEqual(len(failed.exception.report['errors']),1)
            consolidation.assert_not_called()
        self.assertEqual(len(calls),240)
    def test_17_stages_dispatched_and_resume_skips_finished_computation(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'reproducibility').mkdir()
            (root/'reproducibility/requirements-python312.lock.txt').write_text('test')
            state=root/'state'; calls=[]
            proof={'raw':{'raw_dir':str(root),'fingerprint':'rawtest'}}
            def fake_start(cmd,**kw):
                calls.append(cmd[-1]);return self.FakeOwnedProcess(0),kw.get('job'),False
            with patch.object(r,'ROOT',root), patch.object(r,'STATE_DIR',state), \
                 patch.object(r,'preflight',return_value=proof), patch.object(r,'configure'), \
                 patch.object(r,'start_owned_process_tree',side_effect=fake_start):
                r.run_pipeline(root,'r','browser')
                self.assertEqual(calls,list(r.STAGES))
                calls.clear();r.run_pipeline(root,'r','browser')
                self.assertEqual(calls,['verify','package'])
    def test_failed_stage_never_marks_later_stages_complete(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'reproducibility').mkdir()
            (root/'reproducibility/requirements-python312.lock.txt').write_text('test')
            state=root/'state'; calls=[];proof={'raw':{'raw_dir':str(root),'fingerprint':'rawtest'}}
            def fake(cmd,**kw):
                calls.append(cmd[-1])
                code=1 if cmd[-1]=='nls270' else 0
                return self.FakeOwnedProcess(code),kw.get('job'),False
            with patch.object(r,'ROOT',root), patch.object(r,'STATE_DIR',state), \
                 patch.object(r,'preflight',return_value=proof), patch.object(r,'configure'), \
                 patch.object(r,'start_owned_process_tree',side_effect=fake),self.assertRaises(r.ReplicationError):
                r.run_pipeline(root,'r','browser')
            self.assertEqual(calls,['panel','prepare','nls270'])
            self.assertEqual(r.read_json(state/'state.json')['completed'],['panel','prepare'])

class PanelSemantics(unittest.TestCase):
    def load(self):
        import pandas as pd
        return pd.read_csv(r.CONTRACT/'panel_reference_master.csv',dtype={'unit_id':'string'},float_precision='round_trip')
    def test_reference_frame_is_accepted(self):
        self.assertEqual(r.validate_panel_frame(self.load())['master_rows'],3000)
    def test_changed_identifier_is_rejected(self):
        x=self.load();x.loc[0,'unit_id']='BAD'
        with self.assertRaises(r.ReplicationError):r.validate_panel_frame(x)
    def test_changed_numeric_panel_value_is_rejected(self):
        x=self.load();x.loc[0,'inscrits']+=1
        with self.assertRaises(r.ReplicationError):r.validate_panel_frame(x)

class NLSBounds(unittest.TestCase):
    def test_negative_contrast_is_allowed(self):
        import pandas as pd
        x=pd.DataFrame({'estimand_type':['cell_probability','group_contrast'],'estimate':[0.1,-0.4]})
        r.validate_nls_bounds(x)
    def test_negative_probability_is_rejected(self):
        import pandas as pd
        x=pd.DataFrame({'estimand_type':['cell_probability','group_contrast'],'estimate':[-0.1,-0.4]})
        with self.assertRaises(r.ReplicationError):r.validate_nls_bounds(x)

if __name__=='__main__':unittest.main()
