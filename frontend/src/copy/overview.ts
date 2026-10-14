export const overview = {
  title: "Overview",
  attention: {
    title: "Needs attention",
    empty: "Nothing needs attention right now.",
    risk: { critical: "Critical", high: "High", medium: "Medium" },
    line: (name: string, headline: string) => `${name}: ${headline}`,
    moreLines: (count: number) => `${count} more lines at risk in the plan`,
    expiring: (batches: number, days: number) =>
      batches === 1
        ? `1 batch expires within ${days} days`
        : `${batches} batches expire within ${days} days`,
    overdue: (orders: number) => (orders === 1 ? "1 order is late" : `${orders} orders are late`),
    dataErrors: (count: number) =>
      count === 1 ? "1 data problem needs fixing" : `${count} data problems need fixing`,
    decisions: (waiting: number, total: number) =>
      `${waiting} of ${total} lines are waiting for your decision`,
    openLine: "Open",
    openBatches: "See batches",
    openOrders: "See orders",
    openDataNotes: "See notes",
    openPlan: "Open plan",
  },
  kpi: {
    stockValue: "Stock value",
    stockValueHint: "At cost, all products",
    spend: "Suggested spend this week",
    spendBudget: (budget: string) => `Budget ${budget}`,
    spendNoBudget: "No budget set",
    atRisk: "Lines likely to run out",
    atRiskHint: "Critical and high",
    notMoving: "Stock not moving",
    notMovingHint: "Value at cost",
    nearExpiry: "Stock near expiry",
    nearExpiryHint: (batches: number) =>
      batches === 1 ? "Value at cost, 1 batch" : `Value at cost, ${batches} batches`,
    nearExpiryNoBatches: "Value at cost",
  },
  trend: {
    title: "Sales, last 12 weeks",
    summary: (week: string, amount: string) =>
      `Sales were highest in the week of ${week}, at ${amount}.`,
    empty: "There are no sales in the last 12 weeks.",
    axisLabel: "Sales in rupees by week",
    shaded: (events: string[]) => `Shaded weeks: ${events.join(", ")}.`,
    tooltipWeek: (week: string) => `Week of ${week}`,
    tooltipSales: "Sales",
    tooltipUnits: "Units",
  },
  cover: {
    title: "Days of stock by category",
    empty: "Days of stock appear once a plan exists.",
    days: (value: string) => `${value} days`,
    reviewRule: (days: number) => `${days} days`,
    summary: (name: string, days: string) => `${name} has the thinnest cover, about ${days} days.`,
    capped: (cap: number) => `Bars stop at ${cap} days.`,
  },
  plan: {
    title: "This week's plan",
    none: "There is no plan for this week yet.",
    noneHint: "It is created every Monday at 6 am.",
    ready: (lines: number) => `Ready, ${lines} lines to buy`,
    waiting: (waiting: number, total: number) =>
      `Waiting for your decisions: ${waiting} of ${total}`,
    allDecided: (lines: number) => `All ${lines} lines have a decision`,
    topLines: "Largest critical lines",
    open: "Open Monday plan",
    week: (date: string) => `Week of ${date}`,
  },
  activity: {
    title: "Recent activity",
    empty: "Nothing has been recorded yet.",
    billSaved: (bill: string) => `Bill ${bill} saved`,
    billVoided: (bill: string) => `Bill ${bill} voided`,
    goodsReceived: (party: string) => `Goods received from ${party}`,
    orderCreated: (order: string, party: string) => `Order ${order} created for ${party}`,
  },
  loadFailed: "We could not load the overview.",
};
