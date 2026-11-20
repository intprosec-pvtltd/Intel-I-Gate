import {Time} from './ui';
const position=value=>value==null?'Not recorded':`+${Number(value).toFixed(1)} seconds`;
export default function VisitTiming({timing:t}){
 if(!t)return null;
 return <section aria-label="Visit timing" style={{marginBottom:24,paddingBottom:20,borderBottom:'1px solid #dce5e9'}}>
  <h2>{t.test_mode?'Video test details':'Visit times'}</h2>
  <p>Destination: <strong>{t.flat}</strong></p>
  <dl>
   <dt>{t.test_mode?'Entry video position':'Entry time'}</dt>
   <dd>{t.test_mode?position(t.entry_video_seconds):<Time value={t.entry_at}/>}</dd>
   <dt>{t.test_mode?'Exit video position':'Exit time'}</dt>
   <dd>{t.status!=='COMPLETED'?'Awaiting exit':t.test_mode?position(t.exit_video_seconds):<Time value={t.exit_at}/>}</dd>
   <dt>Expected exit</dt><dd><Time value={t.expected_exit_at}/></dd><dt>Entry saved at</dt><dd><Time value={t.saved_at}/></dd>
  </dl>
  {t.exit_method&&<p className="muted">{t.exit_method==='AUTO_TEST_FACE_EXIT'?'Automatically matched from exit test video':t.exit_method==='AUTO_FACE_EXIT'?'Automatically confirmed at exit camera':t.exit_method==='RESIDENT_CONFIRMED'?'Exit confirmed by resident (response time)':'Exit confirmed'}</p>}
  {t.test_mode&&<p className="muted">Video positions are relative to each recording. Real-world entry and exit times are not available.</p>}
 </section>;
}
