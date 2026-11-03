import type { Metadata } from "next";
import { DM_Sans, DM_Mono } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  display: "swap",
});

const dmMono = DM_Mono({
  weight: ["400", "500"],
  subsets: ["latin"],
  variable: "--font-dm-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Invoice Processor · Snowmelt Financial Audit Dashboard",
  description: "Multimodal VLM-powered Invoice Extraction, Math Validation, and Reporting",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="vi"
      className={`${dmSans.variable} ${dmMono.variable} h-full antialiased`}
    >
      <body className="h-screen flex flex-col overflow-hidden text-sm bg-[#f0f2f5] text-[#1e293b]">
        {children}
      </body>
    </html>
  );
}
