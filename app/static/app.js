const state={paused:false,revision:1};
const feedback=document.querySelector('#feedback');
async function request(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.detail||'运行失败，请重试');return data;}
const runBtn=document.querySelector('#run');
if(runBtn){const datasetSel=document.querySelector('#dataset');runBtn.addEventListener('click',async(event)=>{event.target.disabled=true;feedback.textContent='运行中…';try{const source=document.body.dataset.source;const useDataset=datasetSel?datasetSel.value:source;const data=await request(useDataset===source?'/api/runs/'+document.body.dataset.runId+'/rerun':'/api/runs',{dataset:useDataset});feedback.textContent=`批次 ${data.manifest.run_id} · ${data.balance.amount} CNY`;const url=new URL(location.href);if(datasetSel){url.searchParams.set('dataset',datasetSel.value);}url.searchParams.set('run_id',data.manifest.run_id);location.href=url;}catch(error){feedback.textContent=error.message;}finally{event.target.disabled=false;}});}
const pauseBtn=document.querySelector('#pause');
if(pauseBtn)pauseBtn.addEventListener('click',event=>{state.paused=!state.paused;event.target.textContent=state.paused?'继续日志':'暂停日志';const logState=document.querySelector('#log-state');if(logState)logState.textContent=state.paused?'已暂停':'滚动中';});
const filter=document.querySelector('#filter');
if(filter)filter.addEventListener('input',event=>{const text=event.target.value.trim();document.querySelectorAll('.primary-panel tbody tr').forEach(row=>row.hidden=!row.textContent.includes(text));});
const review=document.querySelector('#review');if(review)review.addEventListener('click',async()=>{try{const run=await fetch('/api/runs/'+review.dataset.id).then(r=>r.json());const result=await request('/api/runs/'+review.dataset.id+'/review',{revision:run.revision});feedback.textContent=result.status;}catch(error){feedback.textContent=error.message;}});
const selected=new URL(location.href).searchParams.get('dataset');const globalDataset=document.querySelector('#dataset');if(selected&&globalDataset)globalDataset.value=selected;

const filePicker=document.querySelector('#csv-file');
if(filePicker){
 const editor=document.querySelector('#csv-text');
 filePicker.addEventListener('change',async()=>{const file=filePicker.files[0];if(!file)return;if(file.size>2000000){editor.value='';alert('文件超过2MB，请缩小后导入');return;}const bytes=await file.arrayBuffer();try{editor.value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(e){editor.value=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}});
 document.querySelector('#import-csv').addEventListener('click',async event=>{event.target.disabled=true;try{const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv_text:editor.value})});const data=await response.json();if(!response.ok)throw Error(data.detail);location.href=location.pathname+'?run_id='+data.manifest.run_id;}catch(e){editor.setCustomValidity(e.message);editor.reportValidity();}finally{event.target.disabled=false;}});
 editor.addEventListener('input',()=>editor.setCustomValidity(''));
}
