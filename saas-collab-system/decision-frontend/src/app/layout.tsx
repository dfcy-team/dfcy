import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "经营决策 · SaaS 协同系统",
  description: "接入现有租户、RBAC 与数据范围的经营决策工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
