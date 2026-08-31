(function(){
  "use strict";

  function copy(text, button, reset){
    if(!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(function(){
      if(!button) return;
      var target=button.querySelector('.copy-label')||button;
      var before=target.textContent;
      target.textContent='copied';
      setTimeout(function(){target.textContent=reset||before;},1300);
    });
  }

  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){copy(btn.dataset.copy,btn,'copy');});
  });
  document.querySelectorAll('[data-copy-target]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var el=document.querySelector(btn.dataset.copyTarget);
      if(el) copy(el.innerText,btn,'copy');
    });
  });

  var reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var stages=[1,2,3,4].map(function(n){return document.querySelector('[data-stage="'+n+'"]');});
  var stageLines=Array.prototype.slice.call(document.querySelectorAll('.stage-line'));
  var operator=document.getElementById('operator-card');
  var store=document.getElementById('store-card');
  var storeVersion=document.getElementById('store-version');
  var storeTime=document.getElementById('store-time');
  var changeCopy=document.getElementById('change-copy');
  var eventEl=document.getElementById('flow-event');
  var routes=[1,2,3,4].map(function(n){return document.getElementById('route-agent-'+n);});
  var operatorRoute=document.getElementById('route-operator');
  var agents=[1,2,3,4].map(function(n){
    var el=document.getElementById('agent-'+n);
    return {el:el,version:el.querySelector('.agent-version')};
  });
  if(!operator||!store||!eventEl) return;

  var CHANGES={
    8:'Say the hard number first.',
    9:'Launch EU with trust before growth.',
    10:'Remove “growth first” from principles.'
  };
  var timers=[];

  function clearTimers(){timers.forEach(clearTimeout);timers=[];}
  function later(ms,fn){timers.push(setTimeout(fn,ms));}
  function stage(n){
    stages.forEach(function(el,i){
      el.classList.toggle('is-active',i===n-1);
      el.classList.toggle('is-complete',i<n-1);
    });
    stageLines.forEach(function(el,i){el.classList.toggle('is-on',i<n-1);});
  }
  function agentState(a,v,state){
    a.version.textContent='v'+v;
    a.el.classList.remove('is-waiting','is-fresh','is-aligned');
    if(state) a.el.classList.add(state);
  }
  function routesOff(){
    operatorRoute.classList.remove('is-flowing','is-complete');
    routes.forEach(function(r){r.classList.remove('is-flowing','is-complete');});
  }
  function base(v){
    stage(4); routesOff();
    storeVersion.textContent='v'+v; storeTime.textContent='current';
    operator.classList.remove('is-active'); store.classList.remove('is-active');
    agents.forEach(function(a){agentState(a,v,'is-aligned');});
    eventEl.textContent='All four agents are on v'+v+'.';
  }
  function round(next){
    var prev=next-1;
    routesOff();
    stage(1);
    operator.classList.add('is-active');
    store.classList.remove('is-active');
    changeCopy.textContent=CHANGES[next];
    agents.forEach(function(a){agentState(a,prev,'');});
    eventEl.textContent='The operator changes direction.';

    later(1450,function(){
      stage(2);
      operatorRoute.classList.add('is-flowing');
      eventEl.textContent='Kyno appends v'+next+' without overwriting v'+prev+'.';
    });

    later(2450,function(){
      operator.classList.remove('is-active');
      operatorRoute.classList.remove('is-flowing');
      operatorRoute.classList.add('is-complete');
      store.classList.add('is-active');
      storeVersion.textContent='v'+next;
      storeTime.textContent='new version appended';
      agents.forEach(function(a){agentState(a,prev,'is-waiting');});
    });

    later(3550,function(){
      stage(3);
      eventEl.textContent='Each agent pulls v'+next+' at its own next step.';
    });

    agents.forEach(function(a,i){
      later(3950+i*700,function(){
        routes[i].classList.add('is-flowing');
        agentState(a,prev,'is-waiting');
      });
      later(4400+i*700,function(){
        routes[i].classList.remove('is-flowing');
        routes[i].classList.add('is-complete');
        agentState(a,next,'is-fresh');
      });
    });

    later(6900,function(){
      stage(4);
      store.classList.remove('is-active');
      agents.forEach(function(a){agentState(a,next,'is-aligned');});
      eventEl.textContent='The system is aligned on v'+next+'.';
    });
  }

  if(reduced){
    storeVersion.textContent='v9';
    stage(3);
    agents.forEach(function(a,i){agentState(a,i===3?8:9,i===3?'is-waiting':'is-fresh');});
    routes.slice(0,3).forEach(function(r){r.classList.add('is-complete');});
    eventEl.textContent='Three agents are on v9; the reviewer pulls it at its next step.';
    return;
  }

  function play(){
    clearTimers();
    base(7);
    later(1300,function(){round(8);});
    later(9500,function(){round(9);});
    later(17700,function(){round(10);});
    later(25900,function(){play();});
  }
  play();
})();
