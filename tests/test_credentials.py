import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import warnings

import yaml

from cryoswath_paper_workflow import workflow_support as support


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.private = self.root / 'credentials.yaml'
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def configure(self, data=None, config=None):
        if data is not None:
            self.private.write_text(yaml.safe_dump(data))
        support.configure_credentials(config, credentials_path=self.private)

    def test_private_values_exported_and_public_placeholders_removed(self):
        config = dict(maap_token='', earthdata_username='', earthdata_password='', cores=1)
        self.configure(dict(maap_token='test-token', earthdata_username='test-user', earthdata_password='test-password'), config)
        self.assertEqual(config, dict(cores=1))
        self.assertEqual(os.environ['ESA_MAAP_OFFLINE_TOKEN'], 'test-token')
        self.assertEqual(os.environ['EARTHDATA_USERNAME'], 'test-user')
        self.assertEqual(os.environ['EARTHDATA_PASSWORD'], 'test-password')

    def test_environment_overrides_file_as_complete_pair(self):
        os.environ.update(ESA_MAAP_OFFLINE_TOKEN='env-token', EARTHDATA_USERNAME='env-user', EARTHDATA_PASSWORD='env-password')
        self.configure(dict(maap_token='file-token', earthdata_username='file-user', earthdata_password='file-password'))
        self.assertEqual(os.environ['ESA_MAAP_OFFLINE_TOKEN'], 'env-token')
        self.assertEqual(os.environ['EARTHDATA_USERNAME'], 'env-user')
        self.assertEqual(os.environ['EARTHDATA_PASSWORD'], 'env-password')

    def test_partial_environment_pair_is_not_mixed_with_file(self):
        os.environ['EARTHDATA_USERNAME'] = 'env-user'
        with self.assertRaisesRegex(ValueError, 'same source'):
            self.configure(dict(earthdata_username='file-user', earthdata_password='file-password'))
        self.assertNotIn('EARTHDATA_PASSWORD', os.environ)

    def test_partial_file_pair_rejected(self):
        with self.assertRaisesRegex(ValueError, 'same source'):
            self.configure(dict(earthdata_password='test-password'))

    def test_token_only_and_missing_private_file_are_allowed(self):
        self.configure()
        self.assertNotIn('ESA_MAAP_OFFLINE_TOKEN', os.environ)
        self.configure(dict(maap_token='test-token'))
        self.assertEqual(os.environ['ESA_MAAP_OFFLINE_TOKEN'], 'test-token')

    def test_public_secrets_rejected_without_echoing_them(self):
        config = dict(maap_token='do-not-display', cores=1)
        with self.assertRaises(ValueError) as result:
            self.configure(config=config)
        self.assertNotIn('do-not-display', str(result.exception))
        self.assertEqual(config, dict(cores=1))

    def test_invalid_yaml_error_does_not_echo_secret_line(self):
        self.private.write_text('maap_token: [do-not-display')
        with self.assertRaises(ValueError) as result:
            self.configure()
        self.assertNotIn('do-not-display', str(result.exception))

    def test_invalid_credential_structure_rejected(self):
        for data in [[], 0, ['test-token'], dict(unrecognized='test-token'), dict(maap_token=123)]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.configure(data)

    def test_maap_environment_recognized_without_keyring(self):
        os.environ['ESA_MAAP_OFFLINE_TOKEN'] = 'test-token'
        status = support.resolve_esa_credential_status(home=self.root, config_path=self.root / 'absent.ini', check_keyring=False)
        self.assertTrue(status.available)
        self.assertIn('ESA_MAAP_OFFLINE_TOKEN', status.source)
        self.assertNotIn('test-token', repr(status))

    def test_maap_keyring_recognized(self):
        keyring = types.SimpleNamespace(get_password=lambda service, user: 'test-token' if (service, user) == ('iam.maap.eo.esa.int', 'offline-token') else None)
        with patch.dict(sys.modules, keyring=keyring):
            status = support.resolve_esa_credential_status(home=self.root, config_path=self.root / 'absent.ini')
        self.assertTrue(status.available)
        self.assertEqual(status.source, 'MAAP token in keyring')

    def test_missing_credentials_warn_about_maap(self):
        with patch.object(support, 'missing_local_l1b_track_ids', return_value=['20200802T153552']), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self.assertTrue(support.warn_if_esa_credentials_missing_for_l1b([], home=self.root, config_path=self.root / 'absent.ini', check_keyring=False))
        self.assertIn('ESA_MAAP_OFFLINE_TOKEN', str(caught[0].message))

    def test_cached_tracks_do_not_probe_credentials(self):
        with patch.object(support, 'missing_local_l1b_track_ids', return_value=[]), patch.object(support, 'resolve_esa_credential_status') as resolver:
            self.assertFalse(support.warn_if_esa_credentials_missing_for_l1b([]))
            resolver.assert_not_called()


class CookieCredentialTests(unittest.TestCase):
    def test_wget_receives_only_private_config_path(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('cookie_helper', support.project_path('scripts', 'nsidc_cookies.py'))
        cookie = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cookie)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'log'
            log.touch()
            auth_paths = []
            executable = root / 'bin/wget'
            executable.parent.mkdir()
            executable.touch()
            system_config = root / 'etc/wgetrc'
            system_config.parent.mkdir()
            system_config.write_text('ca_certificate = /test/system-ca.pem\n')
            user_config = root / 'user.wgetrc'
            user_config.write_text('use_proxy = off\n')

            def validate(args, output, log_path):
                self.assertEqual(args[0], '--config')
                auth_path = Path(args[1])
                auth_paths.append(auth_path)
                self.assertEqual(auth_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(auth_path.read_text(), 'ca_certificate = /test/system-ca.pem\n\nuse_proxy = off\n\nhttp_user = test-user\nhttp_password = test-"password\\\n')
                self.assertNotIn('test-user', repr(args))
                return True

            with patch.object(cookie, '_validate_with_wget_auth', side_effect=validate), patch.object(cookie.shutil, 'which', return_value=str(executable)), patch.dict(os.environ, WGETRC=str(user_config)):
                self.assertTrue(cookie._try_username_password_source('environment', 'Environment', 'test-user', 'test-"password\\', root / 'cookies', log))
            self.assertFalse(auth_paths[0].exists())
            self.assertNotIn('--no-check-certificate', cookie._build_common_download_cmd(root / 'target'))


if __name__ == '__main__':
    unittest.main()
