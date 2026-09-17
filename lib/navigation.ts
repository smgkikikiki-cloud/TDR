/** The primary navigation IS the product: the free vehicle database and its
 * comparison tool, then the two subscriber layers. Nothing else belongs here —
 * brands, plants and search are views of the database, not sections of their
 * own, and they are reached from inside it. */
export const primaryNav = [
  { href: "/models", label: "ฐานข้อมูลรถยนต์" },
  { href: "/compare", label: "เปรียบเทียบสเปก" },
  { href: "/reports", label: "ข้อมูลตลาดรถยนต์" },
  { href: "/research", label: "บทวิเคราะห์เชิงลึก" },
];

/** Where the header's account entry points. */
export const memberEntry = { href: "/member/login", label: "เข้าสู่ระบบ" };
