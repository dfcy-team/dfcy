import { describe, expect, it } from 'vitest';
import { flattenMenuItems, menuItems } from '../src/router/menu';

describe('V2.44.33 menu baseline', () => {
  it('keeps the baseline top-level structure and only adds Developer B BD performance', () => {
    expect(menuItems.map((item) => item.label)).toEqual([
      '工作台', '产品开发', '全球刊登', '经营分析', '经营决策', '销售管理', '达人管理',
      '流程协同', '业务协同', 'RPA协同', 'API数据接入', '财务中心', '报表中心', '基础档案',
      '系统治理', '治理与试点'
    ]);

    const development = menuItems.find((item) => item.label === '产品开发');
    expect(development.children.map((item) => item.label)).toEqual([
      '选品提报', '需求审核', '开发项目', '开发产品档案', '成本核算', '销售数据', '选品复盘', '效能看板'
    ]);

    const influencers = menuItems.find((item) => item.label === '达人管理');
    expect(influencers.children.map((item) => item.label)).toEqual([
      '达人档案', '建联任务', '送样履约', 'BD绩效'
    ]);
    expect(flattenMenuItems(menuItems)).toHaveLength(99);
  });
});
