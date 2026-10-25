import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = app.DB
        app.DB = Path(self.tmp.name) / 'test.sqlite3'
        app.init()
    def tearDown(self):
        app.DB = self.old
        self.tmp.cleanup()
    def lead(self):
        app.add({'name':'Example business', 'website':'https://example.com', 'region':'Australia'})
        return app.all_prospects()[0]['id']
    def test_deduplicate_and_draft(self):
        pid = self.lead()
        self.assertFalse(app.add({'name':'Duplicate','website':'https://example.com'}))
        result = app.draft(pid)
        self.assertIn('Example business', result['message'])
        self.assertNotIn('noticed:', result['message'])
        self.assertEqual(len(app.all_prospects()), 1)
    def test_real_findings_persist_and_inform_draft(self):
        pid = self.lead()
        with patch('app.fetch_public', return_value=('https://example.com','<html><title>Example</title><h1>Hello</h1></html>')):
            result = app.analyze(pid)
        self.assertEqual(len(result['findings']),2)
        self.assertIn('meta description', app.draft(pid)['message'])
    def test_private_network_blocked(self):
        for url in ['http://127.0.0.1', 'http://169.254.169.254', 'http://[::1]', 'file:///etc/passwd', 'https://example.com:8000']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.fetch_public(url)
    def test_send_requires_review_and_respects_optout(self):
        pid = self.lead()
        with self.assertRaisesRegex(ValueError,'Reviewed'):
            app.send(pid, {'confirm':True})
        app.update(pid, {'do_not_contact':True})
        with self.assertRaisesRegex(ValueError,'do not contact'):
            app.send(pid, {'confirm':True})
    def test_send_once_and_status_tracking(self):
        pid=self.lead()
        app.draft(pid)
        app.update(pid, {'status':'Reviewed','email':'owner@example.com'})
        config={k:'test' for k in ['GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN']}
        config['GMAIL_SENDER']='sender@example.com'
        with patch.dict('os.environ',config), patch('app.api_request',side_effect=[{'access_token':'token'},{'id':'sent-123'}]) as network:
            self.assertTrue(app.send(pid,{'confirm':True})['sent'])
            self.assertEqual(network.call_count,2)
        self.assertEqual(app.get(pid)['status'],'Contacted')
        app.update(pid, {'status':'Reviewed'})
        with patch.dict('os.environ',config), self.assertRaisesRegex(ValueError,'already has a send attempt'):
            app.send(pid,{'confirm':True})
    def test_ambiguous_send_not_retried(self):
        pid=self.lead(); app.draft(pid)
        app.update(pid,{'status':'Reviewed','email':'owner@example.com'})
        config={k:'test' for k in ['GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN','GMAIL_SENDER']}
        with patch.dict('os.environ',config), patch('app.api_request',side_effect=OSError('timeout')):
            with self.assertRaisesRegex(ValueError,'Check Gmail Sent'):
                app.send(pid,{'confirm':True})
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM sends').fetchone()[0],'Needs manual verification')
    def test_yelp_listing_not_mistaken_for_business_site(self):
        with patch.dict('os.environ',{'YELP_API_KEY':'test'}), patch('app.api_request',return_value={'businesses':[{'id':'one','name':'Business','url':'https://yelp.com/biz/one'}]}):
            results=app.search({'provider':'yelp','region':'United Kingdom','city':'London','term':'salon'})
        self.assertNotIn('website',results[0])
        self.assertEqual(results[0]['source_url'],'https://yelp.com/biz/one')
    def test_missing_credential_explained(self):
        with patch.dict('os.environ',{},clear=True), self.assertRaisesRegex(ValueError,'GOOGLE_PLACES_API_KEY'):
            app.search({'provider':'google','region':'Australia','city':'Sydney','term':'builder'})

if __name__=='__main__': unittest.main()
