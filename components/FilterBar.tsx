export function FilterBar({ filters }: { filters: string[] }) {
  return (
    <div className="filterBar">
      {filters.map((filter) => <button key={filter} type="button">{filter} <span>⌄</span></button>)}
      <button className="clearFilter" type="button">ล้างตัวกรอง</button>
    </div>
  );
}
