import { describe, expect, it } from 'vitest';
import { bundleCsvHeaderIndex, decodeBundleImportFile, parseBundleCsvRecords } from '../src/utils/bundleImportCsv';

describe('组合商品 CSV 读取', () => {
  it('能读取旧模板使用的 GB18030 中文表头', async () => {
    const bytes = new Uint8Array([0xbe, 0xc9, 0x53, 0x50, 0x55, 0xb1, 0xe0, 0xc2, 0xeb]);
    const text = await decodeBundleImportFile({ arrayBuffer: async () => bytes.buffer });
    expect(text).toBe('旧SPU编码');
  });

  it('按原文件行号报告跳过空行和多行引号后的数据', () => {
    const rows = parseBundleCsvRecords('名称,属性编码\r\n\r\n"第一行\r\n第二行",A\r\n商品,0');
    expect(rows.map((row) => row.line)).toEqual([1, 3, 5]);
    expect(rows[1].values).toEqual(['第一行\n第二行', 'A']);
  });

  it('识别必填标记且兼容旧列名', () => {
    const headers = ['*组合商品名称', '*季节编码'];
    expect(bundleCsvHeaderIndex(headers, '组合商品名称')).toBe(0);
    expect(bundleCsvHeaderIndex(headers, '季节编码')).toBe(1);
  });
});
