import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Run with: node --input-type=module -e "import('./tests/test_completion_ui.mjs').then(async m => console.log(await m.runTests()))"
export async function runTests() {
  const html = readFileSync(new URL('../templates/interface.html', import.meta.url), 'utf8');
  const source = html.slice(html.indexOf('let submissionCompleted = false;'),
    html.indexOf('document.getElementById("submit-button").addEventListener'));
  const passed = [];
  const warning = 'Please do not accept any more tasks for this study.';
  function setup(reply, validate = true) {
    class Element {
      constructor(tag) { this.tagName=tag; this.children=[]; this.style={}; this.disabled=false; this.textContent=''; }
      append(...items) { this.children.push(...items); }
      prepend(item) { this.children.unshift(item); }
      replaceChildren(...items) { this.children=items; }
      setAttribute(key,value) { this[key]=value; }
      focus() { this.focused=true; }
      scrollIntoView() {}
    }
    const body = new Element('body');
    const button = new Element('button'); button.id='submit-button'; body.append(button);
    const find = (el,id) => el.id===id ? el : el.children.map(c=>find(c,id)).find(Boolean);
    const text = el => el.textContent + el.children.map(text).join(' ');
    let calls=0;
    const context=vm.createContext({
      document:{body,createElement:tag=>new Element(tag),getElementById:id=>find(body,id)},
      checkScores:()=>validate, collectData:()=>'{"score":7}',
      fetch:async()=>{ calls++; return await reply(); },
      alert:()=>{ throw new Error('Popup must not open'); },
      window:{location:{set href(value) { throw new Error('Must wait for participant to click link'); }}}
    });
    vm.runInContext(source,context);
    return {context,body,button,text:()=>text(body),find:id=>find(body,id),calls:()=>calls,
      submit:()=>vm.runInContext('sendData()',context)};
  }
  for (const more of [true,false]) {
    const ui=setup(async()=>({status:200,json:async()=>({result:'OK',more_tasks_available:more})}));
    await ui.submit();
    assert.ok(ui.text().includes('Submission received'));
    assert.equal(ui.text().includes(warning),!more);
    const panel=ui.find('completion-message');
    const link=panel.children.find(c=>c.tagName==='a');
    assert.equal(link.href,'https://app.prolific.co/submissions/complete?cc=12345');
    assert.equal(link.textContent,'Complete this submission on Prolific');
    assert.equal(panel.focused,true);
    assert.equal(ui.find('submit-button'),undefined);
    await ui.submit(); assert.equal(ui.calls(),1);
    passed.push('Inline completion, correct warning and explicit link: more='+more);
  }
  for (const kind of ['http','network','unconfirmed']) {
    const ui=setup(async()=>{
      if(kind==='network') throw new Error('Offline');
      return {status:kind==='http'?503:200,json:async()=>({result:'not OK'})};
    });
    await ui.submit();
    assert.ok(ui.find('submission-message'));
    assert.equal(ui.find('completion-message'),undefined);
    assert.equal(ui.button.disabled,false);
    await ui.submit(); assert.equal(ui.calls(),2);
    passed.push('Inline failure preserves retry: '+kind);
  }
  let resolve;
  const pending=new Promise(r=>{resolve=r;});
  const ui=setup(()=>pending);
  const first=ui.submit(); await ui.submit();
  assert.equal(ui.calls(),1);
  resolve({status:200,json:async()=>({result:'OK',more_tasks_available:false})});
  await first;
  passed.push('Repeated clicks while saving send only one request');
  const invalid=setup(async()=>{throw new Error('Must not submit');},false);
  await invalid.submit(); assert.equal(invalid.calls(),0); assert.equal(invalid.button.disabled,false);
  passed.push('Invalid answers do not submit or disable retry');
  assert.doesNotMatch(html,/\b(?:alert|confirm|prompt)\s*\(/);
  passed.push('Questionnaire contains no popup calls, including validation and timers');
  for(const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) new vm.Script(match[1]);
  passed.push('All bundled inline scripts parse');
  return passed;
}
