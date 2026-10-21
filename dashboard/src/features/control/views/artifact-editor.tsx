import {
  Button,
  DetailDrawer,
  Input,
  JsonView,
  Select,
  Tabs,
  Textarea,
} from "@/ui"
import type { ManagementClient } from "../model"
import { useEditor } from "../use-editor"

const subjectLabels: Record<string, string> = {
  owner: "主人",
  speaker: "说话人",
  self: "机器人自身",
  world: "外部事实",
  relation: "关系",
  third_party: "第三方",
}

export function ArtifactEditor({
  client,
  id,
  close,
  onSaved,
}: {
  client: ManagementClient
  id: string | null
  close: () => void
  onSaved: () => Promise<void>
}) {
  const vm = useEditor(client, id, onSaved)
  return (
    <DetailDrawer
      open={id !== null}
      onOpenChange={(open) => {
        if (!open && !vm.saving) close()
      }}
      title="编辑与审计"
      description="修订内容、范围与状态；查看版本、来源和账本"
    >
      <div className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">编辑与审计</h2>
          <Button variant="ghost" disabled={vm.saving} onClick={vm.reload}>
            重新加载
          </Button>
        </div>
        <p className="font-mono text-xs wrap-anywhere text-muted-foreground">
          {id}
        </p>
        {vm.attribution && (
          <section className="space-y-3 rounded-xl border bg-secondary/40 p-4">
            <h3 className="font-semibold">主体与时间</h3>
            <dl className="grid grid-cols-2 gap-4 text-xs">
              {[
                ["记忆主体 ID", vm.attribution.subjectId],
                ["说话人标记", vm.attribution.saidBy],
                [
                  "主体类型",
                  subjectLabels[vm.attribution.subjectKind ?? ""] ??
                    vm.attribution.subjectKind,
                ],
                ["事件 / 创建时间", vm.attribution.created],
                ["有效期开始", vm.attribution.validFrom],
                ["有效期结束", vm.attribution.validTo],
              ].map(([label, value]) => (
                <div key={label} className="min-w-0 space-y-1">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="wrap-anywhere">{value || "未记录"}</dd>
                </div>
              ))}
            </dl>
            <p className="text-xs leading-5 text-muted-foreground">
              说话人不一定是记忆主体。新版抽取优先记录事件时间，旧记忆可能仅有创建时间；此处保留原始时间，不补推缺失信息。
              修改 JSON 不会自动重算头部的主体 ID 或时间。
            </p>
          </section>
        )}
        {vm.error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive"
          >
            {vm.error}
          </p>
        )}
        {vm.notice && (
          <p role="status" className="text-sm text-primary">
            {vm.notice}
          </p>
        )}
        {!vm.detail && !vm.error && <p role="status">正在加载详情…</p>}
      </div>
      {vm.detail && (
        <Tabs
          defaultValue="edit"
          items={[
            {
              value: "edit",
              label: "修订",
              content: (
                <div className="space-y-5 p-6">
                  <p className="text-sm text-muted-foreground">
                    {vm.detail.artifact.header.family} · 当前 v
                    {vm.detail.artifact.header.revision}
                    。保存会新增版本，不覆盖历史。
                  </p>
                  <label
                    htmlFor="artifact-payload"
                    className="block space-y-2 text-sm"
                  >
                    <span>记忆内容（JSON）</span>
                    <Textarea
                      id="artifact-payload"
                      aria-label="记忆内容 JSON"
                      className="font-mono text-xs"
                      rows={12}
                      value={vm.payload}
                      onChange={(event) => vm.setPayload(event.target.value)}
                    />
                  </label>
                  <div className="flex flex-wrap gap-3">
                    <Select
                      label="可见范围"
                      value={vm.scope}
                      onValueChange={vm.setScope}
                      options={[
                        { value: "private", label: "私有 private" },
                        { value: "shared", label: "共享 shared" },
                        { value: "shadow", label: "影子 shadow" },
                      ]}
                    />
                    <Select
                      label="记忆状态"
                      value={vm.state}
                      onValueChange={vm.setState}
                      options={
                        vm.detail.artifact.header.state === "merged"
                          ? [{ value: "merged", label: "已合并（保留）" }]
                          : [
                              { value: "active", label: "有效 / 恢复" },
                              { value: "forgotten", label: "遗忘" },
                            ]
                      }
                    />
                  </div>
                  <label
                    htmlFor="artifact-reason"
                    className="block space-y-2 text-sm"
                  >
                    <span>修改原因</span>
                    <Input
                      id="artifact-reason"
                      value={vm.reason}
                      maxLength={300}
                      onChange={(event) => vm.setReason(event.target.value)}
                      placeholder="说明内容修订、遗忘或恢复的原因"
                    />
                  </label>
                  <p className="text-xs leading-6 text-muted-foreground">
                    shared
                    在现有召回规则下跨会话可见。群聊记录的来源会话不等于访问隔离；请在修改范围前核对来源与内容。
                  </p>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={vm.confirmed}
                      onChange={(event) =>
                        vm.setConfirmed(event.target.checked)
                      }
                    />
                    <span>确认本次内容、状态与可见范围的修改</span>
                  </label>
                  <Button
                    disabled={vm.saving || !vm.confirmed || !vm.reason.trim()}
                    onClick={() => {
                      void vm.save()
                    }}
                  >
                    {vm.saving ? "保存中…" : "保存新修订"}
                  </Button>
                </div>
              ),
            },
            {
              value: "history",
              label: "版本与来源",
              content: (
                <div className="space-y-4 p-6">
                  <h3 className="font-semibold">版本快照与 blob</h3>
                  {vm.detail.versions.map((version, index) => (
                    <section
                      key={
                        typeof version["revision"] === "number"
                          ? version["revision"]
                          : index
                      }
                      className="space-y-2"
                    >
                      <JsonView value={version} />
                      <Button
                        variant="outline"
                        onClick={() => {
                          const content = version["content"]
                          if (typeof content === "string")
                            vm.setPayload(content)
                        }}
                      >
                        载入该版本内容到修订草稿
                      </Button>
                    </section>
                  ))}
                  <p className="text-xs text-muted-foreground">
                    载入后返回“修订”检查并保存；恢复旧内容也会产生新版本。
                  </p>
                  <h3 className="font-semibold">不可变来源证据</h3>
                  <JsonView value={vm.detail.sources} />
                  <h3 className="font-semibold">当前头部与 lineage</h3>
                  <JsonView value={vm.detail.artifact.header} />
                </div>
              ),
            },
            {
              value: "ledger",
              label: "变更账本",
              content: (
                <div className="space-y-4 p-6">
                  <p className="text-sm text-muted-foreground">
                    账本只显示实际写入的记录；历史版本存在不代表每次旧写入都记录过账本。
                  </p>
                  <JsonView value={vm.detail.ledger} />
                </div>
              ),
            },
          ]}
        />
      )}
    </DetailDrawer>
  )
}
