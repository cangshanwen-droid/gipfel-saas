import type { Metadata } from "next"
import { AntdRegistry } from "@ant-design/nextjs-registry"
import { AuthProvider } from "@/lib/auth"
import "./globals.css"

export const metadata: Metadata = {
  title: "Gipfel 模拟系统 v2.0",
  description: "基础设施合同管理 + 区域模拟 SaaS 平台",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>
          <AuthProvider>
            {children}
          </AuthProvider>
        </AntdRegistry>
      </body>
    </html>
  )
}
