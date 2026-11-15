import {test} from 'node:test';
import assert from 'node:assert/strict';
import {renderEnergyScene,sceneStyles} from '../energy_pilot/energy_pilot/frontend/energy-scene.js';

const base={pv:4200,house:1100,battery:600,soc:78,ev:2400,grid:-100,has:{pv:true,battery:true,ev:true,grid:true}};
const connections={'pv>house':1100,'pv>batt':600,'pv>ev':2400,'pv>grid':100};
const options={connections,split:v=>[v==null?'–':String(v),'W'],labels:{pv:'Sol',batt:'Batteri',ev:'Bil'}};

test('only installed equipment has artwork, meters and active connections',()=>{
  for(let mask=0;mask<16;mask++){
    const has=Object.fromEntries(['pv','battery','ev','grid'].map((k,i)=>[k,!!(mask&(1<<i))]));
    const html=renderEnergyScene({...base,has},null,options);
    for(const [key,art] of [['pv','solar'],['battery','battery'],['ev','car'],['grid','grid']]){
      assert.equal(html.includes(`/art/${art}.png`),has[key],`${key}, mask ${mask}`);
    }
    assert.equal(html.includes('/art/charger.png'),has.ev);
    for(const key of ['pv','batt','ev','grid']){
      const present=has[{pv:'pv',batt:'battery',ev:'ev',grid:'grid'}[key]];
      assert.equal(html.includes(`data-equipment="${key}"`),present);
    }
    if(!has.pv) assert.ok(!html.includes('data-flow="pv>'));
    if(!has.ev) assert.ok(!html.includes('data-flow="pv>ev"'));
    assert.ok(html.includes('/art/house.png'));
  }
});

test('only supplied active flows animate, including reverse grid and battery directions',()=>{
  assert.ok(!renderEnergyScene(base,null,{...options,connections:{}}).includes('data-flow='));
  for(const key of ['pv>house','batt>house','grid>batt','batt>grid','grid>ev']){
    const html=renderEnergyScene(base,null,{...options,connections:{[key]:1200}});
    assert.ok(html.includes(`data-flow="${key}"`));
    assert.ok(html.includes('ep-current-core'));
  }
});

test('all twelve seasonal and time variants resolve to separate backgrounds',()=>{
  for(const season of ['spring','summer','autumn','winter']) for(const time of ['day','dusk','night']){
    assert.ok(renderEnergyScene(base,{season,time},options).includes(`/art/${season}_${time}.png`));
  }
});

test('Christmas lights coexist with snow and rain rather than replacing weather',()=>{
  for(const [condition,css] of [['snowy','ep-snow'],['rainy','ep-rain'],['fog','ep-fog'],['lightning-rainy','ep-lightning']]){
    const html=renderEnergyScene(base,{season:'winter',time:'night',condition,holiday:{key:'jul',colours:['#fff']}},options);
    assert.ok(html.includes(css));
    assert.ok(html.includes('ep-light'));
  }
  const off=renderEnergyScene(base,null,options);
  assert.ok(!off.includes('class="ep-rain"'));
  assert.ok(!off.includes('class="ep-stars"'));
});

test('holiday families retain their animated treatment',()=>{
  for(const [key,css] of [['nytaar','ep-spark'],['midsummer','ep-ember'],['bonfire','ep-ember'],['carnival','ep-leaf'],['jul','ep-light'],['paaske','ep-light'],['halloween','ep-light'],['national','ep-light'],['thanksgiving','ep-light'],['lunar','ep-light'],['diwali','ep-light'],['eid','ep-light']]){
    assert.ok(renderEnergyScene(base,{holiday:{key},time:'night'},options).includes(css),key);
  }
});

test('labels and scene values are escaped, reduced motion disables all animation',()=>{
  const html=renderEnergyScene(base,{season:'../../private',time:'" onload="bad',outdoor:'<script>'},{...options,labels:{pv:'<img src=x onerror=x>'},format:v=>v});
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img src=x'));
  assert.ok(html.includes('/art/summer_day.png'));
  assert.match(sceneStyles, /prefers-reduced-motion:reduce/);
  assert.match(sceneStyles, /animation:none!important/);
});
