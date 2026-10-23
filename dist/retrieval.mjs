const STOP=new Set('a an the is are was were do does can could would should what which how much many tell me about for of to in on and or with it this that my please be have has i we you from at there your'.split(' '));
export const terms=text=>(text.toLowerCase().match(/[a-z0-9]+/g)||[]).filter(t=>!STOP.has(t));
const ALIASES={pets:'pets pet dog cat animal',pet:'pet pets dog cat animal',deposit:'security deposit refundable refund deductions',rent:'rent monthly payment due',notice:'notice termination vacate tenancy',leave:'notice termination vacate tenancy',parking:'parking bay vehicle',hoa:'association community maintenance rules',guest:'guest guests visitors overnight',repair:'repairs maintenance structural'};
export function retrieve(question,documents,propertyId,limit=3){
  const query=new Set(terms(question).flatMap(t=>[t,...terms(ALIASES[t]||'')]));
  const ranked=[];
  for(const doc of documents.filter(d=>d.property_id===propertyId)) {
    (doc.pages||[]).forEach((text,i)=>{
      const clean=text.replace(/^FICTIONAL DEMONSTRATION (?:DOCUMENT|PROPERTY)\.\s*(?:Not an actual offer or executed lease\.\s*)?/,'');
      const parts=clean.split(/\n\n/).filter(s=>s.trim());
      for(const part of parts){
        const words=new Set(terms(part));const matches=[...query].filter(t=>words.has(t));
        const score=matches.length/Math.sqrt(Math.max(words.size,1));
        if(matches.length)ranked.push({doc_id:doc.id,name:doc.name,page:i+1,text:part,score,property_id:propertyId});
      }
    });
  }
  return ranked.sort((a,b)=>b.score-a.score).slice(0,limit).map((s,i)=>({...s,label:`S${i+1}`}));
}
export function extractiveAnswer(question,documents,propertyId){
  const sources=retrieve(question,documents,propertyId);
  return {sources,mode:'extractive',text:sources.length?'Here’s what the selected property’s documents say:\n\n'+sources.map(s=>`${s.text} [${s.label}]`).join('\n\n'):'I couldn’t find that in this property’s documents. Add the relevant document, or ask about its rent, deposit, notice period, parking, or community rules.'};
}
