"use client"
import { Card, Typography } from "antd"
import AppLayout from "@/components/AppLayout"

export default function StubPage() {
  return (
    <AppLayout>
      <Card><Typography.Title level={4}>占地面积</Typography.Title>
        <Typography.Text type="secondary">此页面正在开发中...</Typography.Text>
      </Card>
    </AppLayout>
  )
}
