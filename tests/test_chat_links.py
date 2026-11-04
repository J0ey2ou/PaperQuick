"""Link dispatch with mocked browsers and an isolated, windowless C# policy."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from embedded_chat import EmbeddedChat
from web_links import safe_web_url,answer_links,open_web_link


class ChatLinkTests(unittest.TestCase):
    def test_literature_links_keep_doi_parentheses_and_drop_markdown_delimiters(self):
        lancet='https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(25)01037-X/fulltext'
        pmc='https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/'
        text='See [Lancet]('+lancet+'), and '+pmc+'.'
        found=list(answer_links(text))
        self.assertEqual([item[2] for item in found],[lancet,pmc])
        self.assertTrue(all(text[start:end]==url for start,end,url in found))

    def test_only_http_and_https_without_credentials_or_control_characters_open(self):
        with patch('webbrowser.open',return_value=True) as browser:
            for url in ('javascript:alert(1)','file:///C:/secret.txt','ms-excel:ofe|u|https://example.org','data:text/html,bad','https://user:password@example.org/','https://example.org/\nextra','https://example.org\\other'):
                self.assertFalse(safe_web_url(url))
                with self.assertRaises(ValueError):open_web_link(url)
            browser.assert_not_called()
            self.assertTrue(open_web_link('https://pmc.ncbi.nlm.nih.gov/articles/PMC123/'))
            browser.assert_called_once()

    def test_native_clicked_link_opens_browser_without_changing_chat_or_prepared_url(self):
        view=EmbeddedChat.__new__(EmbeddedChat);view.events=queue.Queue();view.process=None
        view.status=Mock();view.url='https://chatgpt.com/c/current';view.pending_url='https://chatgpt.com/#paperquick=kept'
        with patch('webbrowser.open',return_value=True) as browser:
            view.events.put({'state':'open-external','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/','userInitiated':True})
            view.poll();browser.assert_called_once_with('https://pmc.ncbi.nlm.nih.gov/articles/PMC123/')
            self.assertEqual(view.url,'https://chatgpt.com/c/current')
            self.assertEqual(view.pending_url,'https://chatgpt.com/#paperquick=kept')
            browser.reset_mock()
            for event in ({'state':'open-external','url':'https://example.org/','userInitiated':False},
                          {'state':'open-external','url':'https://example.org/'},
                          {'state':'open-external','url':'javascript:alert(1)','userInitiated':True}):view.events.put(event)
            view.poll();browser.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Uses the installed Windows C# compiler, no browser')
    def test_native_navigation_policy_for_gestures_platform_routes_login_and_popups(self):
        compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():self.skipTest('C# compiler unavailable')
        base=Path(__file__).resolve().parents[1]
        source=(base/'embedded-browser/EmbeddedChat.cs').read_text('utf-8')
        policy=source.split('// BEGIN NAVIGATION POLICY:',1)[1].split('\n',1)[1].split('// END NAVIGATION POLICY',1)[0]
        cases=[
            ('https://chatgpt.com','https://pmc.ncbi.nlm.nih.gov/articles/PMC123/',True,False,True,'external'),
            ('https://chatgpt.com','https://www.thelancet.com/article/PIIS0140-6736(25)01037-X',True,False,False,'external'),
            ('https://chatgpt.com','https://example.org/',False,False,True,'blocked'),
            ('https://chatgpt.com','https://chatgpt.com/c/next',True,False,False,'embed'),
            ('https://chat.deepseek.com','https://chat.deepseek.com/a/chat/s/next',True,False,False,'embed'),
            ('https://gemini.google.com','https://scholar.google.com/',True,False,False,'external'),
            ('https://chatgpt.com','https://accounts.google.com/signin',True,False,False,'embed'),
            ('https://chatgpt.com','https://accounts.google.com/signin',True,False,True,'login'),
            ('https://chatgpt.com','https://auth.openai.com/callback',False,True,False,'embed'),
            ('https://chatgpt.com','http://example.org/paper',True,False,False,'external')]
        for target in ('javascript:alert(1)','file:///C:/x','data:text/html,x','ms-excel:abc','https://user:pass@example.org/','https://example.org\\x'):
            cases.append(('https://chatgpt.com',target,True,False,True,'blocked'))
        statements=[]
        for chat,target,user,redirect,popup,_ in cases:
            arguments=','.join([json.dumps(chat),json.dumps(target),str(user).lower(),str(redirect).lower(),str(popup).lower()])
            statements.append('Console.WriteLine(ChatNavigationPolicy.Classify('+arguments+'));')
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);code=folder/'Policy.cs';binary=folder/'Policy.exe'
            code.write_text('using System;\n'+policy+'\nclass PolicyTest { static void Main(){'+''.join(statements)+'}}',encoding='utf-8')
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            built=subprocess.run([str(compiler),'/nologo','/target:exe','/out:'+str(binary),str(code)],capture_output=True,text=True,creationflags=flags,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,creationflags=flags,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.splitlines(),[case[-1] for case in cases])


if __name__=='__main__':unittest.main()
