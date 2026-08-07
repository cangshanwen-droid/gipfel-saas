"use client"
import { useEffect, useState } from "react"
import { Card, Table, Button, Modal, Form, Input, InputNumber, message, Space } from "antd"
import { PlusOutlined } from "@ant-design/icons"
import { useAuth } from "@/lib/auth"
import { getRegions, createRegion } from "@/lib/api"
import AppLayout from "@/components/AppLayout"

export default function RegionsPage() {
  const { token } = useAuth()
  const [regions, setRegions] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    if (!token) return
    setLoading(true)
    setRegions(await getRegions(token))
    setLoading(false)
  }

  useEffect(() => { load() }, [token])

  const onCreate = async (values: any) => {
    if (!token) return
    await createRegion(token, values)
    message.success("区域创建成功")
    setModalOpen(false)
    form.resetFields()
    load()
  }

  return (
    <AppLayout>
      <Card title="区域管理" extra={<Button icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新增区域</Button>}>
        <Table dataSource={regions} rowKey="id" loading={loading} pagination={false}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "人口", dataIndex: "population", render: (v: number) => v?.toLocaleString() },
            { title: "人才", dataIndex: "talent_population", render: (v: number) => v?.toLocaleString() },
            { title: "碳排放", dataIndex: "carbon_emissions" },
            { title: "承载力", dataIndex: "population_capacity", render: (v: number) => v?.toLocaleString() },
          ]} />
      </Card>
      <Modal title="新增区域" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        <Form form={form} onFinish={onCreate} layout="vertical">
          <Form.Item name="name" label="区域名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="population" label="人口" initialValue={10000}><InputNumber style={{ width: "100%" }} /></Form.Item>
          <Form.Item name="talent_population" label="人才人口" initialValue={1000}><InputNumber style={{ width: "100%" }} /></Form.Item>
          <Form.Item name="population_capacity" label="人口承载力" initialValue={100000}><InputNumber style={{ width: "100%" }} /></Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
