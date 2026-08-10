
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import os
import re
import shutil
import ast
import json
from datetime import datetime

class SecurityScanner:
    """Python代码安全扫描器 - 检测可疑上传/外泄行为"""

    # 可疑模式定义 (正则表达式)
    SUSPICIOUS_PATTERNS = {
        "网络请求上传文件": [
            r'requests\.post\s*\([^)]*files\s*=',
            r'requests\.put\s*\([^)]*files\s*=',
            r'urllib\.request\.urlopen\s*\([^)]*data\s*=',
        ],
        "读取系统敏感文件": [
            r'open\s*\(\s*["\']*/etc/',
            r'open\s*\(\s*["\']*/proc/',
            r'open\s*\(\s*["\']*/var/',
            r'open\s*\(\s*["\']*/home/[^"\']+',
            r'open\s*\(\s*["\']*C:\\\\',
            r'open\s*\(\s*["\']*\\\\',
        ],
        "socket网络外泄": [
            r'socket\.socket\s*\(',
            r'\.connect\s*\(\s*\(',
            r'\.sendall\s*\(',
            r'\.send\s*\(',
        ],
        "可疑外部域名": [
            r'https?://[^"\'\s)]+\.(tk|ml|ga|cf|top|xyz|click|link|work|date|party|download|racing|win|bid|stream|gdn|men|loan|review|trade|account|science|ninja|space|website|rocks|digital|email|solutions|center|support|phone|tech|systems|network|cloud|app|io|cc|pw|su|biz|info)',
            r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',
            r'https?://[^"\'\s)]+/(upload|collect|exfil|dump|steal|grab|harvest|scrape|gather|send|post|put|receive|callback|beacon|ping|report|log|track|monitor|spy)',
        ],
        "base64编码传输": [
            r'base64\.b64encode\s*\(',
            r'base64\.b64decode\s*\(',
        ],
        "subprocess命令执行": [
            r'subprocess\.run\s*\(',
            r'subprocess\.call\s*\(',
            r'subprocess\.Popen\s*\(',
            r'os\.system\s*\(',
            r'os\.popen\s*\(',
            r'exec\s*\(',
            r'eval\s*\(',
        ],
        "文件遍历收集": [
            r'os\.walk\s*\(',
            r'glob\.glob\s*\(',
            r'pathlib\.Path\s*\([^)]*\.glob',
            r'listdir\s*\(',
            r'scandir\s*\(',
        ],
        "环境变量/密钥窃取": [
            r'os\.environ\[',
            r'os\.environ\.get\s*\(',
            r'os\.environ\.items\s*\(',
            r'os\.getenv\s*\(',
        ],
        "剪贴板操作": [
            r'pyperclip',
            r'clipboard',
            r'win32clipboard',
        ],
        "键盘记录": [
            r'pynput',
            r'keyboard\.Listener',
            r'hook\s*\(',
        ],
    }

    # 需要删除的危险导入
    DANGEROUS_IMPORTS = [
        'socket', 'subprocess', 'urllib.request', 'requests', 'base64',
        'pyperclip', 'pynput', 'keyboard', 'clipboard', 'win32clipboard'
    ]

    def __init__(self):
        self.results = []

    def scan_file(self, filepath):
        """扫描单个文件，返回发现的风险列表"""
        findings = []
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            return [("ERROR", f"无法读取文件: {e}", 0, "")]

        # 检查每个可疑模式
        for category, patterns in self.SUSPICIOUS_PATTERNS.items():
            for pattern in patterns:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        findings.append((
                            "HIGH" if category in ["网络请求上传文件", "socket网络外泄", "subprocess命令执行"] else "MEDIUM",
                            category,
                            line_num,
                            line.strip()
                        ))

        # AST分析：检查函数调用和导入
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self.DANGEROUS_IMPORTS:
                            findings.append(("HIGH", f"危险导入: {alias.name}", node.lineno, f"import {alias.name}"))
                elif isinstance(node, ast.ImportFrom):
                    if node.module in self.DANGEROUS_IMPORTS:
                        findings.append(("HIGH", f"危险导入: {node.module}", node.lineno, f"from {node.module} import ..."))
        except SyntaxError:
            pass

        return findings

    def clean_file(self, filepath, findings):
        """清洗文件 - 移除可疑代码块，返回 (success, cleaned_content)"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except Exception as e:
            return False, str(e)

        # 需要删除的行号集合 (0索引)
        lines_to_remove = set()

        for severity, category, line_num, line_content in findings:
            idx = line_num - 1
            lines_to_remove.add(idx)

            # 如果是函数定义，尝试删除整个函数体
            stripped = line_content.strip()
            if stripped.startswith('def ') or stripped.startswith('class '):
                func_start = idx
                base_indent = len(lines[func_start]) - len(lines[func_start].lstrip())
                for i in range(func_start + 1, len(lines)):
                    line_stripped = lines[i].strip()
                    if not line_stripped or line_stripped.startswith('#'):
                        continue
                    current_indent = len(lines[i]) - len(lines[i].lstrip())
                    if current_indent <= base_indent:
                        break
                    lines_to_remove.add(i)

        # 构建清洗后的代码
        cleaned_lines = []
        for i, line in enumerate(lines):
            if i not in lines_to_remove:
                cleaned_lines.append(line)
            else:
                # 保留空行结构，添加注释标记
                cleaned_lines.append(f"# [SECURITY_CLEANED] 已移除可疑代码: {line}")

        # 移除多余的空行
        cleaned_content = ''.join(cleaned_lines)
        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)

        return True, cleaned_content


class SecurityScannerGUI:
    """图形化安全扫描工具"""

    def __init__(self, root):
        self.root = root
        self.root.title("Python代码安全扫描与清洗工具")
        self.root.geometry("1200x800")
        self.root.configure(bg='#1a1a2e')

        self.scanner = SecurityScanner()
        self.current_file = None
        self.scan_results = {}
        self.scanned_directory = ""

        self.setup_ui()

    def setup_ui(self):
        # 主框架
        main_frame = tk.Frame(self.root, bg='#1a1a2e')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 顶部标题
        title = tk.Label(main_frame, text="Python代码安全扫描与清洗工具", 
                        font=('Microsoft YaHei', 18, 'bold'), 
                        fg='#00d4aa', bg='#1a1a2e')
        title.pack(pady=10)

        # 副标题
        subtitle = tk.Label(main_frame, 
                           text="自动检测可疑上传/外泄行为 | 自动备份为 .bak | 一键清洗",
                           font=('Microsoft YaHei', 10), 
                           fg='#888888', bg='#1a1a2e')
        subtitle.pack(pady=5)

        # 按钮区域
        btn_frame = tk.Frame(main_frame, bg='#1a1a2e')
        btn_frame.pack(pady=15)

        self.btn_scan = tk.Button(btn_frame, text="选择目录扫描", 
                                  command=self.scan_directory,
                                  font=('Microsoft YaHei', 12), 
                                  bg='#0f3460', fg='white',
                                  activebackground='#16213e',
                                  padx=20, pady=8, cursor='hand2')
        self.btn_scan.pack(side=tk.LEFT, padx=10)

        self.btn_clean = tk.Button(btn_frame, text="一键清洗所有", 
                                   command=self.clean_all,
                                   font=('Microsoft YaHei', 12), 
                                   bg='#e94560', fg='white',
                                   activebackground='#c23a51',
                                   padx=20, pady=8, cursor='hand2',
                                   state=tk.DISABLED)
        self.btn_clean.pack(side=tk.LEFT, padx=10)

        self.btn_backup = tk.Button(btn_frame, text="查看备份", 
                                    command=self.show_backups,
                                    font=('Microsoft YaHei', 12), 
                                    bg='#533483', fg='white',
                                    activebackground='#3d2661',
                                    padx=20, pady=8, cursor='hand2',
                                    state=tk.DISABLED)
        self.btn_backup.pack(side=tk.LEFT, padx=10)

        self.btn_report = tk.Button(btn_frame, text="导出报告", 
                                    command=self.export_report,
                                    font=('Microsoft YaHei', 12), 
                                    bg='#2d6a4f', fg='white',
                                    activebackground='#1b4332',
                                    padx=20, pady=8, cursor='hand2',
                                    state=tk.DISABLED)
        self.btn_report.pack(side=tk.LEFT, padx=10)

        # 统计信息
        self.stats_label = tk.Label(main_frame, text="就绪 | 待扫描", 
                                   font=('Microsoft YaHei', 10), 
                                   fg='#00d4aa', bg='#1a1a2e')
        self.stats_label.pack(pady=5)

        # 分割面板
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=10)

        # 左侧：文件列表
        left_frame = tk.Frame(paned, bg='#16213e')
        paned.add(left_frame, weight=1)

        tk.Label(left_frame, text="文件列表", 
                font=('Microsoft YaHei', 12, 'bold'), 
                fg='#00d4aa', bg='#16213e').pack(pady=5)

        # 文件列表带滚动条
        list_frame = tk.Frame(left_frame, bg='#16213e')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_listbox = tk.Listbox(list_frame, 
                                       yscrollcommand=scrollbar.set,
                                       font=('Consolas', 10),
                                       bg='#0f3460', fg='white',
                                       selectbackground='#e94560',
                                       selectforeground='white',
                                       height=20)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)

        # 右侧：详情面板
        right_frame = tk.Frame(paned, bg='#16213e')
        paned.add(right_frame, weight=2)

        # 风险详情
        tk.Label(right_frame, text="风险详情", 
                font=('Microsoft YaHei', 12, 'bold'), 
                fg='#e94560', bg='#16213e').pack(pady=5)

        self.detail_text = scrolledtext.ScrolledText(
            right_frame, 
            font=('Consolas', 10),
            bg='#0f3460', fg='#ff6b6b',
            height=10,
            wrap=tk.WORD
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 代码预览
        tk.Label(right_frame, text="代码预览 (红色 = 可疑代码)", 
                font=('Microsoft YaHei', 12, 'bold'), 
                fg='#00d4aa', bg='#16213e').pack(pady=5)

        self.code_text = scrolledtext.ScrolledText(
            right_frame, 
            font=('Consolas', 10),
            bg='#0f3460', fg='white',
            height=12,
            wrap=tk.NONE
        )
        self.code_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 底部状态栏
        self.status_bar = tk.Label(main_frame, text="准备就绪", 
                                  font=('Microsoft YaHei', 9), 
                                  fg='#888888', bg='#1a1a2e',
                                  anchor=tk.W)
        self.status_bar.pack(fill=tk.X, pady=5)

    def scan_directory(self):
        """扫描选择的目录"""
        directory = filedialog.askdirectory(title="选择要扫描的Python项目目录")
        if not directory:
            return

        self.scanned_directory = directory
        self.scan_results = {}
        self.file_listbox.delete(0, tk.END)
        self.detail_text.delete(1.0, tk.END)
        self.code_text.delete(1.0, tk.END)

        total_files = 0
        risky_files = 0
        total_findings = 0

        self.status_bar.config(text=f"正在扫描: {directory}...")
        self.root.update()

        # 遍历目录
        for root_dir, dirs, files in os.walk(directory):
            # 跳过隐藏目录和venv
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', '__pycache__', 'node_modules']]

            for file in files:
                if file.endswith('.py') and not file.endswith('.bak'):
                    filepath = os.path.join(root_dir, file)
                    total_files += 1

                    findings = self.scanner.scan_file(filepath)

                    if findings:
                        risky_files += 1
                        total_findings += len(findings)
                        self.scan_results[filepath] = findings

                        # 显示在列表中
                        rel_path = os.path.relpath(filepath, directory)
                        risk_level = max([f[0] for f in findings])
                        icon = "[HIGH]" if risk_level == "HIGH" else "[MED]"
                        self.file_listbox.insert(tk.END, f"{icon} {rel_path} ({len(findings)}处风险)")
                        self.file_listbox.itemconfig(tk.END, fg='#ff6b6b' if risk_level == "HIGH" else '#ffd93d')

        # 更新统计
        self.stats_label.config(
            text=f"扫描完成 | 总文件: {total_files} | 风险文件: {risky_files} | 风险点: {total_findings}"
        )

        if risky_files > 0:
            self.btn_clean.config(state=tk.NORMAL)
            self.btn_backup.config(state=tk.NORMAL)
            self.btn_report.config(state=tk.NORMAL)
            self.status_bar.config(text=f"发现 {risky_files} 个风险文件，建议立即清洗！")
            messagebox.showwarning("安全警告", 
                f"发现 {risky_files} 个文件存在可疑上传/外泄行为！\n\n"
                f"共检测到 {total_findings} 处风险点。\n"
                f"请点击【一键清洗所有】进行代码清洗，原文件将自动备份为 .bak")
        else:
            self.status_bar.config(text="未发现可疑代码，项目安全！")
            messagebox.showinfo("扫描结果", "未在项目中检测到可疑的上传或数据外泄行为。")

    def on_file_select(self, event):
        """选择文件时显示详情"""
        selection = self.file_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        filepath = list(self.scan_results.keys())[idx]
        findings = self.scan_results[filepath]

        # 显示风险详情
        self.detail_text.delete(1.0, tk.END)
        for severity, category, line_num, line_content in findings:
            icon = "[HIGH]" if severity == "HIGH" else "[MED]"
            self.detail_text.insert(tk.END, 
                f"{icon} [{severity}] {category}\n"
                f"   第 {line_num} 行: {line_content}\n\n")

        # 显示代码预览
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except:
            lines = []

        self.code_text.delete(1.0, tk.END)
        risky_lines = {f[2] for f in findings}

        for i, line in enumerate(lines, 1):
            prefix = f"{i:4d}| "
            if i in risky_lines:
                self.code_text.insert(tk.END, prefix, 'risk')
                self.code_text.insert(tk.END, line, 'risk')
            else:
                self.code_text.insert(tk.END, prefix + line)

        self.code_text.tag_config('risk', foreground='#ff6b6b', background='#3d0000')

    def clean_all(self):
        """一键清洗所有风险文件"""
        if not self.scan_results:
            return

        if not messagebox.askyesno("确认清洗", 
            "即将清洗所有风险文件中的可疑代码！\n"
            "原文件将自动备份为 .bak 格式。\n\n"
            "是否继续？"):
            return

        cleaned_count = 0
        backup_count = 0
        failed_files = []

        for filepath, findings in self.scan_results.items():
            # 创建备份
            backup_path = filepath + '.bak'
            try:
                shutil.copy2(filepath, backup_path)
                backup_count += 1
            except Exception as e:
                failed_files.append(f"备份失败: {filepath}")
                continue

            # 清洗文件
            success, result = self.scanner.clean_file(filepath, findings)
            if success:
                try:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(result)
                    cleaned_count += 1
                except Exception as e:
                    failed_files.append(f"写入失败: {filepath} - {e}")
            else:
                failed_files.append(f"清洗失败: {filepath} - {result}")

        self.status_bar.config(
            text=f"清洗完成 | 备份: {backup_count} | 清洗: {cleaned_count}"
        )

        msg = f"已成功清洗 {cleaned_count} 个文件！\n已创建 {backup_count} 个 .bak 备份文件。"
        if failed_files:
            msg += f"\n\n失败项:\n" + "\n".join(failed_files[:5])

        messagebox.showinfo("清洗完成", msg)

        # 清空结果，需要重新扫描
        self.scan_results = {}
        self.file_listbox.delete(0, tk.END)
        self.btn_clean.config(state=tk.DISABLED)

    def show_backups(self):
        """显示备份文件信息"""
        backup_files = []
        for filepath in self.scan_results.keys():
            backup_path = filepath + '.bak'
            if os.path.exists(backup_path):
                backup_files.append(backup_path)

        if not backup_files:
            messagebox.showinfo("备份信息", "尚未创建备份文件。")
            return

        info = "已创建的备份文件：\n\n"
        for bp in backup_files:
            size = os.path.getsize(bp)
            info += f"[BACKUP] {bp} ({size} bytes)\n"

        messagebox.showinfo("备份列表", info)

    def export_report(self):
        """导出扫描报告为JSON"""
        if not self.scan_results:
            return

        report = {
            "scan_time": datetime.now().isoformat(),
            "scanned_directory": self.scanned_directory,
            "total_risky_files": len(self.scan_results),
            "total_findings": sum(len(v) for v in self.scan_results.values()),
            "findings": {}
        }

        for filepath, findings in self.scan_results.items():
            rel_path = os.path.relpath(filepath, self.scanned_directory)
            report["findings"][rel_path] = []
            for severity, category, line_num, line_content in findings:
                report["findings"][rel_path].append({
                    "severity": severity,
                    "category": category,
                    "line": line_num,
                    "code": line_content
                })

        # 保存报告
        report_path = os.path.join(self.scanned_directory, f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("报告导出", f"扫描报告已保存到:\n{report_path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"无法保存报告: {e}")


def main():
    root = tk.Tk()
    app = SecurityScannerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
