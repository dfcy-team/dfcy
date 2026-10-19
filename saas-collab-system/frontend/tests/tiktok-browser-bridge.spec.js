import { describe, expect, it, vi } from 'vitest';
import { captureTikTokReceipt, navigateTikTokBridge, TK_RESULT_PATH } from '../src/utils/tiktokBrowserBridge';

describe('TK browser relay isolation', () => {
  it('removes the fragment before handing off one receipt', () => {
    const location = { pathname: TK_RESULT_PATH, hash: '#receipt=FAKE_BODY.FAKE_SIGNATURE', search: '' };
    const history = { state: {}, replaceState: vi.fn() };
    expect(captureTikTokReceipt(location, history)).toBe('FAKE_BODY.FAKE_SIGNATURE');
    expect(history.replaceState).toHaveBeenCalledExactlyOnceWith(history.state, '', TK_RESULT_PATH);
  });
  it.each(['#receipt=one.two&receipt=other.two', '#receipt=', '#code=FAKE_CODE', '#receipt=<script>'])('rejects malformed return material: %s', (hash) => {
    const history = { replaceState: vi.fn() };
    expect(captureTikTokReceipt({ pathname: TK_RESULT_PATH, hash, search: '' }, history)).toBe('');
    expect(history.replaceState).toHaveBeenCalledOnce();
  });
  it('does not touch another platform route', () => {
    const history = { replaceState: vi.fn() };
    expect(captureTikTokReceipt({ pathname: '/callback/shopee', hash: '#receipt=one.two' }, history)).toBe('');
    expect(history.replaceState).not.toHaveBeenCalled();
  });
  it('rejects query data even when clearing history changes the live location', () => {
    const location = { pathname: TK_RESULT_PATH, hash: '#receipt=one.two', search: '?code=FAKE_CODE' };
    const history = { replaceState: () => { location.search = ''; } };
    expect(captureTikTokReceipt(location, history)).toBe('');
  });
  it('navigates in the same tab to the one fixed relay', () => {
    const navigate = vi.fn();
    navigateTikTokBridge('https://dingfengchuangyu.com/saas-tk/start#ticket=one.two', navigate);
    expect(navigate).toHaveBeenCalledExactlyOnceWith('https://dingfengchuangyu.com/saas-tk/start#ticket=one.two');
  });
  it.each(['https://foreign.example.test/saas-tk/start#ticket=one.two', 'http://dingfengchuangyu.com/saas-tk/start#ticket=one.two', 'https://dingfengchuangyu.com/callback#ticket=one.two', 'https://dingfengchuangyu.com/saas-tk/start?ticket=one.two', 'https://dingfengchuangyu.com/saas-tk/start#ticket=one.two&ticket=one.two'])('rejects untrusted navigation: %s', (url) => {
    const navigate = vi.fn();
    expect(() => navigateTikTokBridge(url, navigate)).toThrow();
    expect(navigate).not.toHaveBeenCalled();
  });
});
