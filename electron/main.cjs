'use strict';
const {app, BrowserWindow, Menu, ipcMain, shell} = require('electron');
const {spawn} = require('node:child_process');
const {randomBytes} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const METHODS = new Set([
  'get_state','refresh','search_global_news','save_watchlist','add_tracking','remove_tracking','save_position',
  'delete_position','set_holding_status','save_neutral_pe','save_guidance',
  'save_public_posts','save_network','set_local_model','open_url','analyze_event','translate_event',
  'event_market_context','get_event_intelligence'
]);
let backend = null;
let backendPort = null;
const token = randomBytes(32).toString('hex');
const BACKEND_START_TIMEOUT_MS = 120000;

const frontend = () => app.isPackaged
  ? path.join(process.resourcesPath,'frontend','index.html')
  : path.resolve(__dirname,'..','frontend','index.html');

function startBackend() {
  return new Promise((resolve,reject) => {
    const executable = app.isPackaged
      ? path.join(process.resourcesPath,'backend','hengshi-backend',process.platform==='win32'?'hengshi-backend.exe':'hengshi-backend')
      : path.resolve(__dirname,'..','.venv','Scripts','python.exe');
    const args = app.isPackaged ? [] : [path.resolve(__dirname,'..','electron_backend.py')];
    if (!fs.existsSync(executable)) return reject(new Error('本地数据服务缺失'));
    backend = spawn(executable,args,{
      env:{...process.env,HENGSHI_DATA_DIR:app.getPath('userData'),HENGSHI_IPC_TOKEN:token},
      cwd:app.isPackaged ? process.resourcesPath : path.resolve(__dirname,'..'),
      stdio:['ignore','pipe','pipe'],windowsHide:true
    });
    let ready = false;
    let settled = false;
    let output = '';
    const stdoutTail=[];
    const log = path.join(app.getPath('userData'),'backend.log');
    const finish = error => {
      if (settled)return;
      settled=true;clearTimeout(timeout);
      if (error)reject(error);else resolve();
    };
    const timeout = setTimeout(() => {
      if (!ready && backend && !backend.killed)backend.kill('SIGKILL');
      finish(new Error(`本地数据服务在 ${BACKEND_START_TIMEOUT_MS/1000} 秒内未就绪。最后输出：${[...stdoutTail,output].filter(Boolean).join(' | ').slice(-1200) || '无启动输出'}。诊断日志：${log}`));
    },BACKEND_START_TIMEOUT_MS);
    backend.once('error',error => finish(new Error(`本地数据服务进程无法启动：${error.message}。诊断日志：${log}`)));
    backend.once('exit',(code,signal) => {
      if (!ready)finish(new Error(`本地数据服务提前退出（${signal || `退出码 ${code}`}）。诊断日志：${log}`));
    });
    backend.stdout.on('data',chunk => {
      output += chunk.toString('utf8');
      const lines=output.split(/\r?\n/);output=lines.pop();
      for (const line of lines) {
        if (ready || settled)break;
        try {
          const message=JSON.parse(line);
          const port=message.port;
          if (!Number.isInteger(port) || port<1024 || port>65535)throw new Error('服务端口无效');
          backendPort=port;ready=true;
          probeBackend(port).then(()=>finish(),error=>finish(error));
        } catch (error) {
          stdoutTail.push(line.slice(0,500));if(stdoutTail.length>12)stdoutTail.shift();
          fs.appendFile(log,`stdout: ${line}\n`,()=>{});
        }
      }
    });
    backend.stderr.on('data',chunk => {
      fs.appendFile(log,chunk.toString('utf8'),() => {});
    });
  });
}

async function probeBackend(port) {
  let lastError=null;
  for (let attempt=0;attempt<12;attempt++) {
    try {
      const response=await fetch(`http://127.0.0.1:${port}/health`,{
        headers:{'X-Hengshi-Token':token},signal:AbortSignal.timeout(5000)
      });
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const result=await response.json();
      if(result.ok===true)return;
      throw new Error('健康检查响应无效');
    } catch(error) {lastError=error;await new Promise(resolve=>setTimeout(resolve,500));}
  }
  throw new Error(`本地数据服务已启动但健康检查失败：${lastError?.message || '未知错误'}。诊断日志：${path.join(app.getPath('userData'),'backend.log')}`);
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
