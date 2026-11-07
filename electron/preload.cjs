'use strict';
const {contextBridge, ipcRenderer} = require('electron');

const methods = [
  'get_state','refresh','search_global_news','save_watchlist','save_position',
  'delete_position','set_holding_status','save_neutral_pe','save_guidance',
  'save_network','set_local_model','open_url','analyze_event','translate_event',
  'event_market_context','get_event_intelligence'
];
const api = Object.fromEntries(methods.map(method =>
  [method,(...args) => ipcRenderer.invoke('hengshi:invoke',method,args)]));
contextBridge.exposeInMainWorld('pywebview',{api});
window.addEventListener('DOMContentLoaded',() => {
  window.dispatchEvent(new Event('pywebviewready'));
});
