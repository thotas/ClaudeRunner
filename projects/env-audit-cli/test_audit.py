#!/usr/bin/env python3
"""
test_audit.py - Tests for env-audit CLI
Run with: python test_audit.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import importlib.util
spec = importlib.util.spec_from_file_location("env_audit", Path(__file__).parent / "env-audit.py")
env_audit = importlib.util.module_from_spec(spec)
sys.modules['env_audit'] = env_audit
spec.loader.exec_module(env_audit)


class TestEnvParsing(unittest.TestCase):
    """Test .env file parsing."""
    
    def test_parse_simple_env(self):
        """Test parsing a simple .env file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("DATABASE_URL=postgres://localhost\n")
            f.write("API_KEY=abc123\n")
            f.write("#COMMENT=test\n")
            f.write("\n")
            f.write("SECRET_KEY=mysecret\n")
            f.flush()
            filepath = Path(f.name)
        
        try:
            result = env_audit.parse_env_file(filepath)
            self.assertIn('DATABASE_URL', result)
            self.assertIn('API_KEY', result)
            self.assertIn('SECRET_KEY', result)
            self.assertNotIn('COMMENT', result)  # Comment should be skipped
            self.assertEqual(result['DATABASE_URL'][0], 'postgres://localhost')
            self.assertEqual(result['API_KEY'][0], 'abc123')
        finally:
            os.unlink(f.name)
    
    def test_parse_empty_file(self):
        """Test parsing an empty .env file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            pass
        filepath = Path(f.name)
        
        try:
            result = env_audit.parse_env_file(filepath)
            self.assertEqual(result, {})
        finally:
            os.unlink(f.name)
    
    def test_parse_with_inline_comments(self):
        """Test parsing .env with inline comments."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("API_KEY=abc123 # this is a comment\n")
            f.flush()
            filepath = Path(f.name)
        
        try:
            result = env_audit.parse_env_file(filepath)
            # The value should strip the inline comment
            self.assertEqual(result['API_KEY'][0], 'abc123')
        finally:
            os.unlink(f.name)
    
    def test_parse_with_quoted_values(self):
        """Test parsing .env with quoted values."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('DATABASE_URL="postgres://localhost/db"\n')
            f.write("SECRET_KEY='mysecret'\n")
            f.flush()
            filepath = Path(f.name)
        
        try:
            result = env_audit.parse_env_file(filepath)
            self.assertEqual(result['DATABASE_URL'][0], 'postgres://localhost/db')
            self.assertEqual(result['SECRET_KEY'][0], 'mysecret')
        finally:
            os.unlink(f.name)


class TestMissingVarDetection(unittest.TestCase):
    """Test missing variable detection."""
    
    def test_missing_var_detected(self):
        """Test that missing required vars are detected."""
        env_vars = {
            'DATABASE_URL': ('postgres://localhost', 1)
        }
        required_vars = ['DATABASE_URL', 'API_KEY', 'SECRET_KEY']
        
        missing = env_audit.check_missing_vars(env_vars, required_vars, [])
        
        self.assertEqual(len(missing), 2)
        missing_keys = [m['key'] for m in missing]
        self.assertIn('API_KEY', missing_keys)
        self.assertIn('SECRET_KEY', missing_keys)
    
    def test_no_missing_vars(self):
        """Test when all required vars are present."""
        env_vars = {
            'DATABASE_URL': ('postgres://localhost', 1),
            'API_KEY': ('abc123', 2),
            'SECRET_KEY': ('mysecret', 3)
        }
        required_vars = ['DATABASE_URL', 'API_KEY', 'SECRET_KEY']
        
        missing = env_audit.check_missing_vars(env_vars, required_vars, [])
        
        self.assertEqual(len(missing), 0)
    
    def test_missing_var_high_severity(self):
        """Test that missing vars have high severity."""
        env_vars = {}
        required_vars = ['API_KEY']
        
        missing = env_audit.check_missing_vars(env_vars, required_vars, [])
        
        self.assertEqual(missing[0]['severity'], 'high')


class TestStaleKeyDetection(unittest.TestCase):
    """Test stale key detection."""
    
    def test_stale_key_detected(self):
        """Test that stale keys are detected."""
        env_vars = {
            'OLD_VAR': ('value', 1),
            'ANOTHER_STALE': ('value', 2)
        }
        required_vars = ['DATABASE_URL']
        
        stale = env_audit.check_stale_keys(env_vars, required_vars)
        
        self.assertEqual(len(stale), 2)
        stale_keys = [s['key'] for s in stale]
        self.assertIn('OLD_VAR', stale_keys)
        self.assertIn('ANOTHER_STALE', stale_keys)
    
    def test_common_keys_not_stale(self):
        """Test that common keys like NODE_ENV are not marked stale."""
        env_vars = {
            'NODE_ENV': ('production', 1),
            'DEBUG': ('false', 2),
            'PORT': ('3000', 3),
            'PATH': ('/usr/bin', 4)
        }
        required_vars = ['DATABASE_URL']
        
        stale = env_audit.check_stale_keys(env_vars, required_vars)
        
        stale_keys = [s['key'] for s in stale]
        self.assertNotIn('NODE_ENV', stale_keys)
        self.assertNotIn('DEBUG', stale_keys)
        self.assertNotIn('PORT', stale_keys)
        self.assertNotIn('PATH', stale_keys)
    
    def test_required_keys_not_stale(self):
        """Test that keys in required_vars are not marked stale."""
        env_vars = {
            'DATABASE_URL': ('postgres://localhost', 1)
        }
        required_vars = ['DATABASE_URL', 'API_KEY']
        
        stale = env_audit.check_stale_keys(env_vars, required_vars)
        
        self.assertEqual(len(stale), 0)


class TestDuplicateDetection(unittest.TestCase):
    """Test duplicate definition detection."""
    
    def test_duplicate_detected(self):
        """Test that duplicates across files are detected."""
        all_env_vars = {
            'API_KEY': [
                ('value1', Path('/path/to/first.env')),
                ('value2', Path('/path/to/second.env'))
            ]
        }
        
        duplicates = env_audit.check_duplicates(all_env_vars)
        
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]['key'], 'API_KEY')
        self.assertEqual(duplicates[0]['count'], 2)
    
    def test_no_duplicates(self):
        """Test when there are no duplicates."""
        all_env_vars = {
            'API_KEY': [('value1', Path('/path/to/first.env'))],
            'SECRET_KEY': [('value2', Path('/path/to/second.env'))]
        }
        
        duplicates = env_audit.check_duplicates(all_env_vars)
        
        self.assertEqual(len(duplicates), 0)


class TestSecretDetection(unittest.TestCase):
    """Test secret pattern detection."""
    
    def test_secret_pattern_detected(self):
        """Test that secrets are detected."""
        value = "Bearer abc123xyz"
        patterns = [r'bearer', r'secret']
        
        detected = env_audit.detect_secrets(value, patterns)
        
        self.assertIn('bearer', detected)
    
    def test_no_secret_detected(self):
        """Test normal value without secrets."""
        value = "postgres://localhost"
        patterns = [r'password', r'secret']
        
        detected = env_audit.detect_secrets(value, patterns)
        
        self.assertEqual(len(detected), 0)


class TestFileFinding(unittest.TestCase):
    """Test .env file discovery."""
    
    def test_find_env_files(self):
        """Test finding .env files in a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            Path(tmpdir, '.env').touch()
            Path(tmpdir, '.env.local').touch()
            Path(tmpdir, 'config.env').touch()
            Path(tmpdir, 'somefile.txt').touch()
            
            # Create subdirectory
            subdir = Path(tmpdir, 'subdir')
            subdir.mkdir()
            Path(subdir, '.env').touch()
            
            patterns = ['.env*', '*.env*']
            found = env_audit.find_env_files(tmpdir, patterns)
            
            # Should find .env, .env.local, config.env, and subdir/.env
            self.assertGreaterEqual(len(found), 3)


class TestReportGeneration(unittest.TestCase):
    """Test report generation."""
    
    def setUp(self):
        self.sample_results = {
            'scan_time': '2024-01-15T10:30:00',
            'directory': '/test/path',
            'files_scanned': 2,
            'files': [
                {'path': '/test/.env', 'variables': {'API_KEY': 'abc'}}
            ],
            'issues': {
                'missing': [
                    {'key': 'SECRET_KEY', 'type': 'missing', 'severity': 'high', 'message': 'Required variable missing'}
                ],
                'stale': [
                    {'key': 'OLD_VAR', 'type': 'stale', 'severity': 'medium', 'message': 'Not in required', 'line': 1}
                ],
                'duplicates': [],
                'secrets': []
            },
            'summary': {
                'total_issues': 1,
                'high_severity': 1,
                'medium_severity': 1,
                'low_severity': 0
            }
        }
    
    def test_json_report_generation(self):
        """Test JSON report generation."""
        report = env_audit.generate_json_report(self.sample_results)
        data = json.loads(report)
        
        self.assertEqual(data['summary']['total_issues'], 1)
        self.assertEqual(data['summary']['high_severity'], 1)
    
    def test_markdown_report_generation(self):
        """Test Markdown report generation."""
        report = env_audit.generate_markdown_report(self.sample_results)
        
        self.assertIn('# Environment Audit Report', report)
        self.assertIn('**Total Issues:** 1', report)
        self.assertIn('SECRET_KEY', report)
        self.assertIn('Missing Required Variables', report)
    
    def test_html_report_generation(self):
        """Test HTML report generation with dark theme."""
        report = env_audit.generate_html_report(self.sample_results)
        
        self.assertIn('<html', report)
        self.assertIn('<title>Environment Audit Report</title>', report)
        self.assertIn('--bg-primary: #0f0f0f', report)  # Dark theme
        self.assertIn('SECRET_KEY', report)
        self.assertIn('Missing Required Variables', report)
    
    def test_html_report_contains_summary_cards(self):
        """Test HTML summary cards."""
        report = env_audit.generate_html_report(self.sample_results)
        
        self.assertIn('Total Issues', report)
        self.assertIn('High Severity', report)
        self.assertIn('Medium Severity', report)


class TestScanIntegration(unittest.TestCase):
    """Integration tests for full scan."""
    
    def test_full_scan_with_issues(self):
        """Test full directory scan with issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .env file with issues
            with open(Path(tmpdir, '.env'), 'w') as f:
                f.write("DATABASE_URL=postgres://localhost\n")
                f.write("OLD_VAR=stale\n")
            
            # Create config
            config = {
                'required_vars': ['DATABASE_URL', 'API_KEY', 'SECRET_KEY'],
                'env_file_patterns': ['.env*'],
                'known_secret_patterns': ['password', 'secret']
            }
            
            results = env_audit.scan_directory(tmpdir, config)
            
            self.assertEqual(results['files_scanned'], 1)
            self.assertGreaterEqual(results['summary']['total_issues'], 1)
            # Should detect missing API_KEY and SECRET_KEY
            missing_keys = [m['key'] for m in results['issues']['missing']]
            self.assertIn('API_KEY', missing_keys)
            self.assertIn('SECRET_KEY', missing_keys)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""
    
    def test_empty_directory(self):
        """Test scanning empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                'required_vars': ['API_KEY'],
                'env_file_patterns': ['.env*'],
                'known_secret_patterns': []
            }
            
            results = env_audit.scan_directory(tmpdir, config)
            
            self.assertEqual(results['files_scanned'], 0)
            self.assertEqual(results['summary']['total_issues'], 0)
    
    def test_nonexistent_directory(self):
        """Test scanning nonexistent directory."""
        config = {
            'required_vars': [],
            'env_file_patterns': ['.env*'],
            'known_secret_patterns': []
        }
        
        results = env_audit.scan_directory('/nonexistent/path/12345', config)
        
        self.assertEqual(results['files_scanned'], 0)
    
    def test_multiline_values(self):
        """Test handling of values with equals signs."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("DATABASE_URL=postgres://user:pass@host:5432/db?option=value\n")
            f.flush()
            filepath = Path(f.name)
        
        try:
            result = env_audit.parse_env_file(filepath)
            # Should parse correctly, splitting on first =
            self.assertIn('DATABASE_URL', result)
        finally:
            os.unlink(f.name)


if __name__ == '__main__':
    unittest.main()