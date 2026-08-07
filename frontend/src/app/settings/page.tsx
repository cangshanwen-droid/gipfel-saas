"use client"
import { useEffect, useState } from "react"
import { Card, Typography, Button, message, Space, Descriptions } from "antd"
import { DownloadOutlined } from "@ant-design/icons"
import { useAuth } from "@/lib/auth"
import { getExcelExportUrl } from "@/lib/api"
import AppLayout from "@/components/AppLayout"

export default function SettingsPage() {
  const { token, user } = useAuth()
  const [loading, setLoading] = useState(false)

  const handleExport = () => {
    if (!token) return
    window.open(getExcelExportUrl(token), "_blank")
    message.success("Excel 导出已开始下载")
  }

  return (
    <AppLayout>
      <Card title="数据管理" style={{ marginBottom: 16 }}>
        <Button icon={<DownloadOutlined />} loading={loading} onClick={handleExport}>
          导出所有数据到 Excel
        </Button>
      </Card>
      <Card title="关于系统">
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="系统名称">Gipfel 模拟系统</Descriptions.Item>
          <Descriptions.Item label="版本">2.0.0 SaaS</Descriptions.Item>
          <Descriptions.Item label="技术栈">FastAPI + Next.js + PostgreSQL</Descriptions.Item>
          <Descriptions.Item label="公式引擎">Gipfel 商业模拟 3.0</Descriptions.Item>
          <Descriptions.Item label="当前用户">{user?.username} ({user?.role})</Descriptions.Item>
        </Descriptions>
      </Card>
    </AppLayout>
  )
}
