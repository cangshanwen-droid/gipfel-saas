"use client"

import React from "react"
import { usePathname, useRouter } from "next/navigation"
import { Layout, Menu, Button, Typography, ConfigProvider, theme } from "antd"
import {
  DashboardOutlined, EnvironmentOutlined, FileTextOutlined,
  TeamOutlined, BankOutlined, CalculatorOutlined,
  LineChartOutlined, SettingOutlined, LogoutOutlined,
  ExportOutlined, AreaChartOutlined
} from "@ant-design/icons"
import { useAuth } from "@/lib/auth"

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: "/dashboard", icon: <DashboardOutlined />, label: "仪表盘" },
  { key: "/regions", icon: <EnvironmentOutlined />, label: "区域管理" },
  { key: "/contracts", icon: <FileTextOutlined />, label: "合同管理" },
  { key: "/companies", icon: <TeamOutlined />, label: "公司管理" },
  { key: "/infra-calc", icon: <BankOutlined />, label: "基建计算" },
  { key: "/calculate", icon: <CalculatorOutlined />, label: "模拟计算" },
  { key: "/trends", icon: <LineChartOutlined />, label: "趋势分析" },
  { key: "/land-area", icon: <AreaChartOutlined />, label: "占地面积" },
  { key: "/accounts", icon: <BankOutlined />, label: "财务账户" },
  { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
]

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { user, logout } = useAuth()

  const selectedKey = menuItems.find(item => pathname.startsWith(item.key))?.key || "/dashboard"

  return (
    <ConfigProvider theme={{ algorithm: theme.defaultAlgorithm }}>
      <Layout style={{ minHeight: "100vh" }}>
        <Sider width={220} style={{ background: "#fff", borderRight: "1px solid #f0f0f0" }}>
          <div style={{ padding: "16px", textAlign: "center", borderBottom: "1px solid #f0f0f0" }}>
            <Typography.Title level={5} style={{ margin: 0 }}>Gipfel 模拟系统</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>v2.0 SaaS</Typography.Text>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => router.push(key)}
            style={{ borderRight: 0, marginTop: 8 }}
          />
        </Sider>
        <Layout>
          <Header style={{
            background: "#fff", padding: "0 24px",
            display: "flex", justifyContent: "space-between", alignItems: "center",
            borderBottom: "1px solid #f0f0f0"
          }}>
            <span />
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Typography.Text>👤 {user?.username} ({user?.role})</Typography.Text>
              <Button icon={<LogoutOutlined />} onClick={logout} type="text">退出</Button>
            </div>
          </Header>
          <Content style={{ padding: 24, background: "#f5f5f5", overflow: "auto" }}>
            {children}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}
