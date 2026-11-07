'use strict';
const {app, BrowserWindow, Menu, ipcMain, shell} = require('electron');
const {spawn} = require('node:child_process');
const {randomBytes} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const METHODS = new Set([
  'get_state','refresh','search_global_news','save_watchlist','save_position',
  'delete_position','set_holding_status','save_neutral_pe','save_guidance',
  'save_network','set_local_model','open_url','analyze_event','translate_event',
  'event_market_context','get_event_intelligence'
]);
let backend = null;
let backendPort = null;
const token = randomBytes(32).toString('hex');

const frontend = () => app.isPackaged
  ? path.join(process.resourcesPath,'frontend','index.html')
  : path.resolve(__dirname,'..','frontend','index.html');

function startBackend() {
  return new Promise((resolve,reject) => {
    const executable = app.isPackaged
      ? path.join(process.resourcesPath,'backend','hengshi-backend')
      : path.resolve(__dirname,'..','.venv','Scripts','python.exe');
    const args = app.isPackaged ? [] : [path.resolve(__dirname,'..','electron_backend.py')];
    if (!fs.existsSync(executable)) return reject(new Error('本地数据服务缺失'));
    backend = spawn(executable,args,{
      env:{...process.env,HENGSHI_DATA_DIR:app.getPath('userData'),HENGSHI_IPC_TOKEN:token},
      cwd:app.isPackaged ? process.resourcesPath : path.resolve(__dirname,'..'),
      stdio:['ignore','pipe','pipe'],windowsHide:true
    });
    let ready = false;
    let output = '';
    const timeout = setTimeout(() => {if (!ready) reject(new Error('本地数据服务启动超时'));},30000);
    backend.once('error',error => {clearTimeout(timeout);reject(error);});
    backend.once('exit',() => {if (!ready){clearTimeout(timeout);reject(new Error('本地数据服务启动失败'));}});
    backend.stdout.on('data',chunk => {
      output += chunk.toString('utf8');
      const newline = output.indexOf('\n');
      if (newline<0 || ready) return;
      const line = output.slice(0,newline);
      output = output.slice(newline+1);
      try {
        const port = JSON.parse(line).port;
        if (!Number.isInteger(port) || port<1024 || port>65535) throw new Error('服务端口无效');
        backendPort = port;
        ready = true;
        clearTimeout(timeout);
        resolve();
      } catch (error) {clearTimeout(timeout);reject(error);}
    });
    backend.stderr.on('data',chunk => {
      const log = path.join(app.getPath('userData'),'backend.log');
      fs.appendFile(log,chunk.toString('utf8'),() => {});
    });
  });
}

function createWindow() {
  const window = new BrowserWindow({
    width:1280,height:820,minWidth:950,minHeight:640,
    title:'衡势',backgroundColor:'#f4f8f9',
    webPreferences:{preload:path.join(__dirname,'preload.cjs'),
                    nodeIntegration:false,contextIsolation:true,sandbox:true}
  });
  const allowed = pathToFileURL(frontend()).href;
  window.webContents.setWindowOpenHandler(({url}) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return {action:'deny'};
  });
  window.webContents.on('will-navigate',(event,url) => {
    if (url.split('#')[0]!==allowed) event.preventDefault();
  });
  window.loadFile(frontend());
}

function installMenu() {
  const template = [];
  if (process.platform === 'darwin') {
    template.push({label:'衡势',submenu:[
      {role:'about',label:'关于衡势'}, {type:'separator'},
      {role:'hide',label:'隐藏衡势'}, {role:'hideOthers',label:'隐藏其他'},
      {role:'unhide',label:'显示全部'}, {type:'separator'},
      {role:'quit',label:'退出衡势'}]});
  }
  template.push({label:'编辑',submenu:[
    {role:'undo',label:'撤销'}, {role:'redo',label:'重做'}, {type:'separator'},
    {role:'cut',label:'剪切'}, {role:'copy',label:'复制'},
    {role:'paste',label:'粘贴'}, {role:'selectAll',label:'全选'}]});
  template.push({label:'窗口',submenu:[
    {role:'minimize',label:'最小化'}, {role:'zoom',label:'缩放'},
    ...(process.platform==='darwin' ? [{type:'separator'},{role:'front',label:'前置全部窗口'}] : [])]});
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

ipcMain.handle('hengshi:invoke',async (event,method,args) => {
  const origin = event.senderFrame?.url?.split('#')[0];
  if (origin!==pathToFileURL(frontend()).href || !METHODS.has(method)
      || !Array.isArray(args) || args.length>3 || !backendPort)
    throw new Error('操作未授权');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(),190000);
  try {
    const response = await fetch(`http://127.0.0.1:${backendPort}/invoke`,{
      method:'POST',headers:{'Content-Type':'application/json','X-Hengshi-Token':token},
      body:JSON.stringify({method,args}),signal:controller.signal
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '本地分析失败');
    return result.value;
  } finally {clearTimeout(timeout);}
});

app.whenReady().then(async () => {
  try {installMenu();await startBackend();createWindow();}
  catch (error) {
    const {dialog} = require('electron');
    dialog.showErrorBox('衡势启动失败',String(error.message || error));
    app.quit();
  }
  app.on('activate',() => {if (BrowserWindow.getAllWindows().length===0 && backendPort) createWindow();});
});
app.on('before-quit',() => {if (backend && !backend.killed) backend.kill();});
app.on('window-all-closed',() => {if (process.platform!=='darwin') app.quit();});
