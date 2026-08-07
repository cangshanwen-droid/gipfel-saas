"use client"

import { useEffect, useState } from "react"
import { Card, Statistic, Row, Col, Spin, Table } from "antd"
import { EnvironmentOutlined, FileTextOutlined, TeamOutlined, SmileOutlined } from "@ant-design/icons"
import { useAuth } from "@/lib/auth"
import { getDashboardSummary, getRegions } from "@/lib/api"
import AppLayout from "@/components/AppLayout"

export default function DashboardPage() {
  const { token } = useAuth()
  const [summary, setSummary] = useState<any>(null)
  const [regions, setRegions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) return
    Promise.all([
      getDashboardSummary(token),
      getRegions(token),
    ]).then(([s, r]) => {
      setSummary(s)
      setRegions(r)
    }).finally(() => setLoading(false))
  }, [token])

  if (!token) return null

  return (
    <AppLayout>
      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card><Statistic title="区域总数" value={summary?.total_regions || 0} prefix={<EnvironmentOutlined />} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="合同数量" value={summary?.total_contracts || 0} prefix={<FileTextOutlined />} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="合作公司" value={summary?.total_companies || 0} prefix={<TeamOutlined />} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="平均幸福度" value={summary?.avg_happiness || 0} suffix="分" prefix={<SmileOutlined />} /></Card>
          </Col>
        </Row>

        <Card title="区域概览">
          <Table
            dataSource={regions}
            rowKey="id"
            pagination={false}
            columns={[
              { title: "区域", dataIndex: "name", key: "name" },
              { title: "人口", dataIndex: "population", key: "population", render: (v: number) => v?.toLocaleString() },
              { title: "人才", dataIndex: "talent_population", key: "talent", render: (v: number) => v?.toLocaleString() },
              { title: "碳排放", dataIndex: "carbon_emissions", key: "carbon", render: (v: number) => v?.toLocaleString() },
              { title: "幸福度", dataIndex: "current_happiness", key: "happiness", render: (v: any) => v ? v.toFixed(1) : "未计算" },
              { title: "就业率", dataIndex: "current_employment_rate", key: "employment", render: (v: any) => v ? v.toFixed(1) + "%" : "未计算" },
            ]}
          />
        </Card>
      </Spin>
    </AppLayout>
  )
}
