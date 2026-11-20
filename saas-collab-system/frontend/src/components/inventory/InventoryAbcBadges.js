import { h } from 'vue';
const labels = {new: "新品观察", no_sales: "无有效销售贡献", unavailable: "未分类"};
function gradeText(grade, reference) {
    if (reference === "new" && grade === "unavailable") return "新品观察（参考）";
    if (reference && ["A", "B", "C"].includes(reference) && grade === "unavailable") return "参考 " + reference;
    return labels[grade] || grade || "未分类";
}

const partGrade = value => ({no_sales:"无正贡献",unavailable:"未分类",new:"新品"}[value] || value || "—");
const continuityText = value => ({sustained:"持续销售",suspected_concentration:"疑似集中成交，需复核",intermittent_or_unproven:"持续性待观察"}[value] || "持续性待观察");
const reasonText = value => ({revenue_A:"销售额贡献A",units_A_with_sustained_sales:"销量A且持续销售",units_A_without_sufficient_clean_continuity:"销量A但持续性或成交集中情况待观察",revenue_or_units_B:"销售额或销量为B",both_revenue_and_units_C:"两个分项均为C",incomplete_sales_history:"销售资料尚未齐全",incomplete_history_prevents_reference_C:"资料不足，综合等级暂不定为C",suspected_order_or_day_concentration:"存在集中成交迹象，需人工复核",maturity_unknown:"首次销售日期尚未确认",new_product_observation:"仍在新品观察期",no_positive_net_sales_or_units:"净销售额和有效销量均无正贡献，单独观察",abc_component_unavailable:"分项资料不足"}[value] || value);

export default {
    props: {row: {type: Object, default: () => ({})}, entityType: {type: String, required: true}},
    setup(props) {
        return () => {
            const data = props.row.abc || {};
            if (data.classification_basis !== "composite" || data.policy_version !== "composite_revenue_units_v1_20261120") return h("span", {style:"font-size:12px;color:#64748b"}, "综合分类更新中");
            const parent = props.entityType === "spu";
            const values = [["SPU", data.spu_grade, data.spu_reference_grade]];
            if (!parent) values.push(["SKU", data.sku_grade, data.sku_reference_grade]);
            let title = "数据截止 " + (data.cutoff_date || "尚未计算") + (data.status === "partial" ? "；资料尚未齐全，显示参考等级" : "") + (data.stale ? "；等待新批次" : "");
            if (data.sku_first_sale_date) title += "；SKU 本国首销 " + data.sku_first_sale_date;
            if (data.spu_first_sale_date) title += "；SPU 本国首销 " + data.spu_first_sale_date;
            for (const key of ["sku", "spu"]) {
                const candidate = data[key + "_candidate_grade"];
                if (["A", "B", "C"].includes(candidate) && candidate !== data[key + "_grade"] && data.status === "ready") title += "；" + key.toUpperCase() + " 候选 " + candidate + "，已连续 " + data[key + "_candidate_streak"] + "/" + (data.stability_days || 3) + " 天";
            }
            const evidence = parent ? data.spu_evidence : data.sku_evidence; if(evidence) title += "；销售额 " + partGrade(evidence.revenue_grade) + "；销量 " + partGrade(evidence.units_grade) + "；" + continuityText(evidence.continuity_label) + "；" + (evidence.reasons || []).map(reasonText).join("、");
            if (evidence) title += "；近12周成交 " + (evidence.active_weeks_last12 ?? "—") + " 周、近4周 " + (evidence.active_weeks_last4 ?? "—") + " 周";
            return h("div", {style: "display:flex;gap:5px;flex-wrap:wrap", title}, values.map(([label, grade, reference]) => h("span", {style: "font-size:12px;white-space:nowrap;border:1px solid " + (reference && (grade === "unavailable" || data.status === "partial") ? "#f0d59f" : "#dbe5f2") + ";border-radius:4px;padding:2px 6px;background:" + (grade === "A" && data.status !== "partial" ? "#edf8ef" : reference && (grade === "unavailable" || data.status === "partial") ? "#fff8e9" : "#f3f6fa") + ";color:#405676"}, label + " 综合 " + gradeText(data.status === "partial" ? "unavailable" : grade, reference))).concat(evidence ? [h("small", {style:"font-size:12px;color:#64748b;flex-basis:100%"}, "销售额 " + partGrade(evidence.revenue_grade) + " · 销量 " + partGrade(evidence.units_grade) + " · " + continuityText(evidence.continuity_label))] : []));
        };
    }
};

