# SPDX-License-Identifier: MIT
"""Chronological presentation preserves original timestamps and incident evidence."""
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gui_fixture import load

START='2026-01-01T00:28:55+01:00'
TIMEOUT='2026-01-01T01:02:14+01:00'
END='2026-01-01T01:12:39+01:00'

class OutcomeTimes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.b=load('web_broker');self.p=patch.object(self.b.s,'STATE_DIR',self.root);self.p.start();self.addCleanup(self.p.stop)
        self.incident=dict(id='synthetic',first_failure=START,confirmed_at=START,first_detail='Disk missing',phase='done',outcome='Storage AUTO-RECOVERED',completed_at=END,
            return_deadline=dict(reported_at=TIMEOUT,outcome='Storage RECOVERY FAILED — Drive return timeout',notification='sent'))
        self.h=self.b.History(self.root/'history.sqlite3')
    def saved(self,value=None):
        p=self.root/'state.json';p.write_text(json.dumps(dict(incident=value or self.incident)));return p
    def test_late_outcome_sorts_before_timeout_without_changing_original_evidence(self):
        p=self.saved();before=p.read_bytes();self.h.capture_incident(self.incident)
        rows=self.h.events();self.assertEqual([x['time'] for x in rows],[END,TIMEOUT])
        self.assertEqual([x['outage_started'] for x in rows],[START,START]);self.assertEqual(p.read_bytes(),before)
        with self.h.connect() as db:raw=dict(db.execute('SELECT id,at FROM events'))
        self.assertEqual(raw,{'synthetic':START,'synthetic-return-timeout':TIMEOUT})
        self.assertEqual(self.h.events(),rows)
    def test_existing_archived_row_gets_only_derived_metadata(self):
        p=self.root/'incidents';p.mkdir();file=p/'synthetic.json';file.write_text(json.dumps(self.incident));before=file.read_bytes()
        self.h.record('synthetic',START,self.incident['outcome'],['Existing evidence kept exactly.'])
        with self.h.connect() as db:original=db.execute('SELECT * FROM events').fetchall()
        rows=self.h.events();self.assertEqual(rows[0]['time'],END);self.assertEqual(file.read_bytes(),before)
        with self.h.connect() as db:self.assertEqual(db.execute('SELECT * FROM events').fetchall(),original)
    def test_broker_offline_at_completion_updates_presentation_from_archive(self):
        active=copy.deepcopy(self.incident);active.pop('completed_at');active.pop('outcome');active.pop('return_deadline');active['phase']='wait1'
        self.h.capture_incident(active);folder=self.root/'incidents';folder.mkdir();(folder/'synthetic.json').write_text(json.dumps(self.incident))
        rows=self.h.events();self.assertEqual(rows[0]['time'],END);self.assertEqual(rows[0]['title'],self.incident['outcome'])
        self.assertEqual(len(rows),2)
    def test_missing_archive_can_use_exact_cached_outcome_time(self):
        self.h.record('cached',START,'Recovered',['Original evidence','Outcome recorded: '+END])
        rows=self.h.events();self.assertEqual(rows[0]['time'],END);self.assertEqual(rows[0]['outage_started'],START)
        with self.h.connect() as db:self.assertEqual(db.execute('SELECT at FROM events').fetchone()[0],START)
    def test_missing_or_invalid_outcome_is_not_invented(self):
        for value in (None,'bad','2026-01-01T01:12:39'):
            i=copy.deepcopy(self.incident);i['completed_at']=value;i.pop('return_deadline');self.saved(i)
            row=self.h.events()[0];self.assertEqual(row['time'],START)
    def test_actual_chronology_across_utc_offsets_and_fleet_sort(self):
        self.h.record('later','2026-01-01T00:10:00+00:00','Later',[])
        self.h.record('earlier','2026-01-01T01:05:00+01:00','Earlier',[])
        self.assertEqual([x['title'] for x in self.h.events()],['Later','Earlier'])
        self.assertGreater(self.b.History.sort_key('2026-01-01T00:10:00+00:00'),self.b.History.sort_key('2026-01-01T01:05:00+01:00'))
    def test_retention_uses_outcome_time_not_old_outage_time(self):
        for number in range(205):self.h.record(str(number),'2025-12-31T23:%02d:00+00:00'%(number%60),'Old',[])
        self.saved();rows=self.h.events(limit=200);self.assertEqual(len(rows),200)
        self.assertEqual([x['time'] for x in rows[:2]],[END,TIMEOUT])
    def test_plain_action_records_keep_existing_shape(self):
        self.h.record('action',END,'Manual action',['Verified'])
        self.assertEqual(self.h.events(),[dict(time=END,title='Manual action',detail='Verified')])

if __name__=='__main__':unittest.main()
