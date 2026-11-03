import { CanonicalInvoice } from '@/types/invoice';

export const FALLBACK_INVOICES: CanonicalInvoice[] = [
  {
    source_file: '08.Aug 2026/01. Invoices/Baldor/Baldor - IV101-0029021609.pdf',
    vendor_name: 'Baldor Specialty Foods Inc.',
    invoice_no: 'IV101-0029021609',
    invoice_date: '2026-08-01',
    due_date: '2026-08-25',
    currency: 'USD',
    category: 'Nguyên vật liệu thực phẩm',
    doc_type: 'goods_invoice',
    subtotal: '97.21',
    tax: '0.00',
    discount: '0.00',
    grand_total: '97.21',
    status: 'VERIFIED',
    review_reasons: [],
    line_items: [
      { item_name: 'Juice Lemon 6x32 oz Orchid Island', qty: '1.00', unit: 'CTN', unit_price: '33.99', line_total: '33.99', kind: 'goods' },
      { item_name: 'Juice Orange Blood 6x12 oz Natalies', qty: '1.00', unit: 'CTN', unit_price: '23.09', line_total: '23.09', kind: 'goods' },
      { item_name: 'Juice Apple Fuji 6x12 oz Red Jacket', qty: '1.00', unit: 'CTN', unit_price: '15.29', line_total: '15.29', kind: 'goods' },
      { item_name: 'Lemonade Zinger Less Sugar 6x12 oz', qty: '1.00', unit: 'CTN', unit_price: '14.59', line_total: '14.59', kind: 'goods' },
      { item_name: 'Melons Watermelon Sangria Seeded', qty: '1.00', unit: 'EACH', unit_price: '10.25', line_total: '10.25', kind: 'goods' }
    ]
  },
  {
    source_file: '08.Aug 2026/01. Invoices/Asscociated - 5.29USD - 03.08.2026.HEIC',
    vendor_name: 'ASSOCIATED of Greenpoint',
    invoice_no: '0142',
    invoice_date: '2026-08-03',
    due_date: '2026-08-03',
    currency: 'USD',
    category: 'Nguyên vật liệu thực phẩm',
    doc_type: 'receipt',
    subtotal: '5.29',
    tax: '0.00',
    discount: '0.00',
    grand_total: '5.29',
    status: 'VERIFIED',
    review_reasons: [],
    line_items: [
      { item_name: 'MCK ROSEMARY LEAVES', qty: '1', unit: 'EA', unit_price: '5.29', line_total: '5.29', kind: 'goods' }
    ]
  },
  {
    source_file: '08.Aug 2026/01. Invoices/Con Edision - Jul26.jpeg',
    vendor_name: 'conEdison',
    invoice_no: '57711-73004-4',
    invoice_date: '2026-07-30',
    due_date: '2026-09-01',
    currency: 'USD',
    category: 'Điện nước',
    doc_type: 'utility_bill',
    subtotal: '90.14',
    tax: '0.00',
    discount: '0.00',
    grand_total: '90.14',
    status: 'VERIFIED',
    review_reasons: [],
    charges: [
      { description: 'Past Due Balance (Kỳ trước)', amount: '26.16' },
      { description: 'Current Electric & Gas Charges (Phát sinh mới)', amount: '63.98' }
    ],
    line_items: []
  },
  {
    source_file: '08.Aug 2026/01. Invoices/FARMS2YOU, LLC - 432660222.pdf',
    vendor_name: 'FARMS2YOU, LLC',
    invoice_no: '432660222',
    invoice_date: '2026-08-12',
    due_date: '2026-08-19',
    currency: 'USD',
    category: 'Nguyên vật liệu thực phẩm',
    doc_type: 'goods_invoice',
    subtotal: '275.74',
    tax: '0.00',
    discount: '0.00',
    grand_total: '275.74',
    status: 'VERIFIED',
    review_reasons: [],
    line_items: [
      { item_name: 'Churchtown Dairy - Ground Beef 10LB', qty: '1', unit: 'CS', unit_price: '120.00', line_total: '120.00', kind: 'goods' },
      { item_name: 'Ronnybrook Farm Dairy - Butter 8LB', qty: '1', unit: 'CS', unit_price: '64.00', line_total: '64.00', kind: 'goods' },
      { item_name: 'Chaseholm Farm Creamery - Camembert', qty: '1', unit: 'EA', unit_price: '50.71', line_total: '50.71', kind: 'goods' },
      { item_name: '*Credit Card Processing Fee', qty: '1', unit: 'FEE', unit_price: '8.03', line_total: '8.03', kind: 'fee' },
      { item_name: '*Order Transaction Fee', qty: '1', unit: 'FEE', unit_price: '3.00', line_total: '3.00', kind: 'fee' }
    ]
  },
  {
    source_file: '08.Aug 2026/01. Invoices/Webstaurant store - 129017763.pdf',
    vendor_name: 'WebstaurantStore',
    invoice_no: '129017763',
    invoice_date: '2026-08-08',
    due_date: '2026-08-08',
    currency: 'USD',
    category: 'Bao bì/vật dụng',
    doc_type: 'goods_invoice',
    subtotal: '206.95',
    tax: '20.31',
    discount: '0.00',
    grand_total: '249.12',
    status: 'REVIEW_NEEDED',
    review_reasons: [
      'Bảng kê có 2 cột giá (Member Price $16.49 vs Regular $17.95), nghi lệch đơn giá chiết khấu',
      'Chênh lệch số học Tier 1 trên dòng Pizza Box (1.46 > tolerance 0.015)'
    ],
    line_items: [
      { item_name: 'Choice 12x12 Kraft Pizza Box 50/Bundle', qty: '1', unit: 'BDL', unit_price: '16.49', line_total: '17.95', kind: 'goods' },
      { item_name: 'Hoffmaster Natural Onyx Dinner Napkin 300/Case', qty: '2', unit: 'CS', unit_price: '63.99', line_total: '139.34', kind: 'goods' },
      { item_name: 'EcoChoice Plant Fiber Take-Out Container 125/Case', qty: '1', unit: 'CS', unit_price: '25.49', line_total: '27.75', kind: 'goods' }
    ]
  },
  {
    source_file: '08.Aug 2026/01. Invoices/Whole Foods - 50.86USD - 59882.png',
    vendor_name: 'WHOLE FOODS MARKET',
    invoice_no: '59882',
    invoice_date: '2020-08-26',
    due_date: '2020-08-26',
    currency: 'USD',
    category: 'Nguyên vật liệu thực phẩm',
    doc_type: 'receipt',
    subtotal: '50.86',
    tax: '0.00',
    discount: '0.00',
    grand_total: '50.86',
    status: 'REVIEW_NEEDED',
    review_reasons: [
      'Ngày hóa đơn (2020-08-26) nằm ngoài kỳ kế toán tháng 2026-08 (Cho phép: 17/06/2026 đến 15/10/2026)'
    ],
    line_items: [
      { item_name: 'ORGANIC HEIRLOOM TOMATOES', qty: '2.4', unit: 'LB', unit_price: '6.99', line_total: '16.78', kind: 'goods' },
      { item_name: 'ORGANIC HEAVY CREAM', qty: '4', unit: 'QT', unit_price: '4.99', line_total: '19.96', kind: 'goods' },
      { item_name: 'ARTISAN SOURDOUGH BREAD', qty: '2', unit: 'EA', unit_price: '7.06', line_total: '14.12', kind: 'goods' }
    ]
  }
];
