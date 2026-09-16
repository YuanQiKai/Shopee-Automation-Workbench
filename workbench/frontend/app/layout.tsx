import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'Meeya · 菲律宾选品工作台',description:'来源可追查，成本可复算，决策由你审核'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="zh-CN"><body>{children}</body></html>}
