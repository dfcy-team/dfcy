import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import html2canvas from 'html2canvas';
import {captureWorkspace,visibleDetails} from '../src/components/issueTracking/capture';
vi.mock('html2canvas',()=>({default:vi.fn()}));
let root;
beforeEach(()=>{
 document.body.innerHTML='<main id="workspace-content"><p>可见业务明细</p><div style="display:none"><span>CSS隐藏秘密</span></div><span hidden>隐藏数据</span><span data-tracking-private>私人令牌</span><input value="password-secret"><nav>导航内容</nav><button>操作按钮</button><p id="outside">屏幕外内容</p></main>';
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({left:0,top:0,right:300,bottom:200,width:300,height:200});
 root=document.querySelector('main');Object.defineProperty(root,'clientWidth',{value:300});Object.defineProperty(root,'clientHeight',{value:200});
 document.querySelector('#outside').getBoundingClientRect=()=>({left:2000,right:2100,top:0,bottom:100,width:100,height:100});
});
afterEach(()=>{vi.restoreAllMocks();vi.clearAllMocks();document.body.innerHTML='';});
describe('页面采集隐私边界',()=>{
 it('仅提取当前可见业务文字，过滤隐藏、敏感输入、导航与视口外内容',()=>{expect(visibleDetails()).toBe('可见业务明细');});
 it('DOM截图排除敏感控件，关闭日志且不污染canvas',async()=>{
  html2canvas.mockResolvedValue({toBlob:cb=>cb(new Blob(['png'],{type:'image/png'}))});
  const blob=await captureWorkspace();expect(blob.size).toBeGreaterThan(0);
  const options=html2canvas.mock.calls[0][1];expect(options).toMatchObject({logging:false,useCORS:true,allowTaint:false,scale:1});
  expect(options.ignoreElements(document.querySelector('input'))).toBe(true);expect(options.ignoreElements(document.querySelector('[hidden]'))).toBe(true);
 });
 it('空白导出不能误判成功，明细为空给出可操作提示',async()=>{
  html2canvas.mockResolvedValue({toBlob:cb=>cb(null)});await expect(captureWorkspace()).rejects.toThrow('截图失败');
  root.innerHTML='<input value="private">';expect(()=>visibleDetails()).toThrow('没有可采集');
 });
});
