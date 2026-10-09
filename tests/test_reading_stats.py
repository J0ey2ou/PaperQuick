from pathlib import Path
import sys,tempfile,unittest
from datetime import date,datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from library_core import Library
from reading_stats import ReadingClock,daily_recap,recap_text
from references import parse_references


class ReadingStatsTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'build'/'stats-tests';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.directory=Path(self.tmp.name)/'store';self.lib=Library(self.directory)
        self.rid=self.lib.save({'title':'Reading fixture','abstract':'An existing local abstract.','notes':'A local note.'})
    def tearDown(self):self.lib.close();self.tmp.cleanup()
    def test_only_continuous_foreground_time_counts(self):
        day=date(2026,10,8);start=datetime.combine(day,datetime.min.time()).timestamp()+3600
        clock=ReadingClock(lambda:self.directory)
        clock.tick(self.rid,True,start,0);clock.tick(self.rid,True,start+1,1)
        clock.tick(self.rid,False,start+2,2);clock.tick(self.rid,False,start+60,60)
        clock.tick(self.rid,True,start+61,61);clock.tick(self.rid,True,start+62,62)
        clock.tick(self.rid,True,start+3662,3662);clock.tick(self.rid,True,start+3663,3663);clock.stop()
        recap=daily_recap(self.lib,day);self.assertEqual(recap['seconds'],3);self.assertEqual(recap['count'],1)
        self.assertIn('An existing local abstract.',recap_text(recap));self.assertEqual(daily_recap(self.lib,day-timedelta(days=1))['count'],0)
    def test_midnight_splits_time(self):
        day=date(2026,10,8);start=datetime.combine(day+timedelta(days=1),datetime.min.time()).timestamp()-1
        clock=ReadingClock(lambda:self.directory)
        for i in range(3):clock.tick(self.rid,True,start+i,i)
        clock.stop();self.assertEqual(daily_recap(self.lib,day)['seconds'],1);self.assertEqual(daily_recap(self.lib,day+timedelta(days=1))['seconds'],1)
    def test_original_reference_numbers_are_preserved(self):
        refs=parse_references('References\n[7] Doe, J. (2024). Protein structure analysis in population research. DOI: 10.9999/a\n[12] Roe, A. (2023). Protein structure prediction in global health research. DOI: 10.9999/b\n')
        self.assertEqual([r['number'] for r in refs],['7','12'])

if __name__=='__main__':unittest.main()
