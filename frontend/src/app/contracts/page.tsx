"use client"
import { Card, Typography } from "antd"
import AppLayout from "@/components/AppLayout"

function StubPage({ title }: { title: string }) {
  return (
    <AppLayout>
      <Card><Typography.Title level={4}>{title}</Typography.Title>
        <Typography.Text type="secondary">此页面正在开发中...</Typography.Text>
      </Card>
    </AppLayout>
  )
}

export default function ContractsPage() { return <StubPage title="合同管理" /> }
