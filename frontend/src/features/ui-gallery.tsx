import { useState, type ReactNode } from "react";
import { Button, TextButton } from "@/components/ui/button";
import { Checkbox, Segmented, Switch, TabPanel, Tabs } from "@/components/ui/controls";
import {
  Banner,
  EmptyState,
  ErrorBanner,
  KpiStrip,
  Mono,
  Panel,
  ProvenanceTag,
  RiskText,
  Skeleton,
  StatusChip,
} from "@/components/ui/display";
import { NumberField, SelectField, TextareaField, TextField } from "@/components/ui/field";
import { ConfirmDialog, Dialog, Drawer, Menu, Tip } from "@/components/ui/overlay";
import { Combobox, CommandPalette, DateField, PackStepper, notify } from "@/components/ui/pickers";
import { DataTable, Pagination } from "@/components/ui/table";
import { common } from "@/copy/common";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

const rows = [
  { id: "1", sku: "FA-031", name: "Black pepper 50 g", qty: "17", price: "68.00" },
  { id: "2", sku: "FA-010", name: "Chana dal 500 g", qty: "0", price: "62.00" },
];

/** Every primitive and state on one page, for visual review. Development only. */
export default function UiGallery() {
  const [tab, setTab] = useState("one");
  const [dialog, setDialog] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [date, setDate] = useState("2026-10-12");
  const [units, setUnits] = useState(20);
  const [mode, setMode] = useState<"cash" | "upi" | "card">("cash");
  const [checked, setChecked] = useState(true);
  const [on, setOn] = useState(true);
  const [pick, setPick] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-4xl space-y-10 px-6 py-8">
      <h1 className="text-xl font-semibold">Component gallery</h1>

      <Section title="Buttons">
        <div className="flex flex-wrap gap-3">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="destructive-filled">Confirm destructive</Button>
          <Button variant="primary" loading>
            Loading
          </Button>
          <Button disabled>Disabled</Button>
          <Button size="sm">Small</Button>
          <Button size="lg">Large</Button>
          <TextButton>Text action</TextButton>
        </div>
      </Section>

      <Section title="Fields">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Name" hint="Helper text sits below." />
          <TextField label="With an error" error="Enter a name." defaultValue="x" />
          <TextField label="Optional field" optional />
          <TextField label="Disabled" disabled defaultValue="Locked" />
          <NumberField label="Quantity" suffix="packs" defaultValue="12" />
          <SelectField label="Select" defaultValue="b">
            <option value="a">First</option>
            <option value="b">Second</option>
          </SelectField>
          <DateField label="Date" value={date} onChange={setDate} />
          <TextareaField label="Notes" optional />
        </div>
        <div className="flex flex-wrap items-center gap-6">
          <Checkbox checked={checked} onCheckedChange={setChecked} label="Checkbox" />
          <Switch checked={on} onCheckedChange={setOn} label="Switch" />
          <Segmented
            label="Payment"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: "cash", label: "Cash" },
              { value: "upi", label: "UPI" },
              { value: "card", label: "Card" },
            ]}
          />
        </div>
        <div className="max-w-xs">
          <Combobox
            value={pick}
            onChange={setPick}
            options={["Biscuits", "Namkeen", "Tea"]}
            onQueryChange={() => {}}
            itemKey={(x) => x}
            itemLabel={(x) => x}
            placeholder="Pick a category"
          />
        </div>
        <PackStepper value={units} packSize={10} onChange={setUnits} ariaLabel="Order quantity" />
      </Section>

      <Section title="Status, risk, provenance">
        <div className="flex flex-wrap items-center gap-4">
          <StatusChip>Draft</StatusChip>
          <StatusChip tone="ok">Received</StatusChip>
          <StatusChip tone="info">Sent</StatusChip>
          <StatusChip tone="medium">Part received</StatusChip>
          <StatusChip tone="critical">Void</StatusChip>
          <RiskText level="critical" label="Critical" />
          <RiskText level="high" label="High" />
          <RiskText level="medium" label="Medium" />
          <RiskText level="low" label="Low" />
          <ProvenanceTag kind="observed" label="Recorded" explanation="Taken from your records." />
          <ProvenanceTag
            kind="calculated"
            label="Worked out"
            explanation="Calculated from your records."
          />
          <ProvenanceTag
            kind="assumed"
            label="Assumed"
            explanation="Not set, so a default is used."
          />
          <Mono>B2610-00412</Mono>
        </div>
      </Section>

      <Section title="Banners, empty state, skeleton">
        <Banner>Information banner.</Banner>
        <Banner tone="warning">Warning banner.</Banner>
        <ErrorBanner
          message="We could not load this."
          onRetry={() => {}}
          retryLabel={common.retry}
        />
        <Panel>
          <EmptyState
            title="No bills yet for these dates."
            hint="Change the dates or add a bill."
            action={<Button>Add a bill</Button>}
          />
        </Panel>
        <div className="space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </Section>

      <Section title="KPI strip">
        <KpiStrip
          items={[
            { label: "Stock value", value: "₹1.9 lakh", hint: "At cost" },
            { label: "Suggested spend", value: "₹54,650", hint: "Budget ₹55,000" },
            { label: "Lines likely to run out", value: "15" },
            { label: "Stock not moving", value: "₹7,307" },
            { label: "Stock near expiry", value: "₹14,666" },
          ]}
        />
      </Section>

      <Section title="Table">
        <DataTable
          caption="Example"
          columns={[
            { key: "name", header: "Product", cell: (r) => r.name },
            { key: "sku", header: "SKU", cell: (r) => <Mono>{r.sku}</Mono> },
            { key: "qty", header: "Stock", numeric: true, cell: (r) => r.qty },
            { key: "price", header: "Price", unit: "₹", numeric: true, cell: (r) => r.price },
          ]}
          rows={rows}
          rowId={(r) => r.id}
          footer={<Pagination page={1} pageSize={25} total={2} onPageChange={() => {}} />}
        />
        <DataTable
          caption="Loading"
          columns={[{ key: "a", header: "Loading state", cell: () => null }]}
          rows={[]}
          rowId={() => ""}
          loading
          skeletonRows={3}
        />
      </Section>

      <Section title="Tabs and overlays">
        <Tabs
          label="Example tabs"
          value={tab}
          onValueChange={setTab}
          items={[
            { value: "one", label: "Buy", count: 41 },
            { value: "two", label: "Watch", count: 9 },
          ]}
        >
          <TabPanel value="one">First panel</TabPanel>
          <TabPanel value="two">Second panel</TabPanel>
        </Tabs>
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => setDialog(true)}>Dialog</Button>
          <Button onClick={() => setConfirm(true)}>Confirm dialog</Button>
          <Button onClick={() => setDrawer(true)}>Drawer</Button>
          <Button onClick={() => setPalette(true)}>Command palette</Button>
          <Button onClick={() => notify.success("Saved.")}>Toast</Button>
          <Button onClick={() => notify.error("We could not save this.")}>Error toast</Button>
          <Tip label="A short explanation.">
            <Button>Tooltip</Button>
          </Tip>
          <Menu
            trigger={<Button>Menu</Button>}
            items={[
              { label: "Edit", onSelect: () => {} },
              { label: "Delete", destructive: true, onSelect: () => {} },
            ]}
          />
        </div>
      </Section>

      <Dialog
        open={dialog}
        onOpenChange={setDialog}
        title="Dialog title"
        footer={
          <Button variant="primary" onClick={() => setDialog(false)}>
            Save
          </Button>
        }
      >
        <TextField label="Field in a dialog" />
      </Dialog>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Void this bill?"
        body="The stock is added back and the bill no longer counts in sales. This cannot be undone."
        confirmLabel="Void bill"
        destructive
        onConfirm={() => setConfirm(false)}
      />
      <Drawer open={drawer} onOpenChange={setDrawer} title="Drawer">
        <p className="p-4 text-base">Drawer content.</p>
      </Drawer>
      <CommandPalette
        open={palette}
        onOpenChange={setPalette}
        pages={[{ id: "p", label: "Overview", onSelect: () => {} }]}
        products={[]}
        onQueryChange={() => {}}
        copy={common.commandPalette}
      />
    </div>
  );
}
