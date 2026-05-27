from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List

from behavioral_password_core import (
    DEFAULT_STORAGE,
    SampleSummary,
    delete_profile,
    evaluate_sample,
    finalize_sample,
    format_explanation,
    get_profile,
    list_usernames,
    migrate_plaintext_profiles,
    upsert_profile,
    verify_phrase,
)


WINDOW_TITLE = "行为口令本地演示系统"
RECOMMENDED_SAMPLES = 5
UI_FONT = ("Microsoft YaHei UI", 13)
UI_FONT_BOLD = ("Microsoft YaHei UI", 13, "bold")
TITLE_FONT = ("Microsoft YaHei UI", 22, "bold")
RESULT_FONT = ("Microsoft YaHei UI", 20, "bold")
INPUT_FONT = ("Consolas", 22)
LIST_FONT = ("Consolas", 14)


class TypingCapture:
    CONTROL_KEYS = {
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Caps_Lock",
        "Tab",
        "Escape",
        "Return",
        "Left",
        "Right",
        "Up",
        "Down",
        "Home",
        "End",
        "Insert",
        "Prior",
        "Next",
    }

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.started_at = None
        self.ended_at = None
        self.dwell_times: List[float] = []
        self.flight_times: List[float] = []
        self.correction_count = 0
        self.last_printable_down = None
        self.active_keys: dict[int, float] = {}

    def on_key_press(self, event: tk.Event) -> None:
        if event.keysym in self.CONTROL_KEYS:
            return

        now = self._clock()
        if self.started_at is None:
            self.started_at = now
        self.ended_at = now

        if event.keysym in {"BackSpace", "Delete"}:
            self.correction_count += 1
            return

        if len(event.char) == 1 and event.char.isprintable():
            if self.last_printable_down is not None:
                self.flight_times.append(max(0.0, now - self.last_printable_down))
            self.last_printable_down = now
            self.active_keys[event.keycode] = now

    def on_key_release(self, event: tk.Event) -> None:
        now = self._clock()
        self.ended_at = now
        down_time = self.active_keys.pop(event.keycode, None)
        if down_time is not None:
            self.dwell_times.append(max(0.01, now - down_time))

    def build_summary(self, final_text: str) -> SampleSummary:
        return finalize_sample(
            final_text=final_text,
            dwell_times=self.dwell_times[:],
            flight_times=self.flight_times[:],
            correction_count=self.correction_count,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )

    @staticmethod
    def _clock() -> float:
        return tk._get_default_root().tk.call("after", "info") or 0.0


class BehavioralPasswordApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1180x780")
        self.root.minsize(1080, 720)

        self.storage_path = Path(DEFAULT_STORAGE)
        self.enrollment_samples: List[SampleSummary] = []
        self.enroll_capture = TypingCapture()
        self.verify_capture = TypingCapture()
        self.verify_attempt_finished = False

        migrate_plaintext_profiles(self.storage_path)
        self._configure_style()
        self._build_layout()
        self._refresh_profiles()

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=UI_FONT)
        style.configure("TButton", font=UI_FONT, padding=(14, 8))
        style.configure("TEntry", font=UI_FONT, padding=6)
        style.configure("TCombobox", font=UI_FONT, padding=6)
        style.configure("TNotebook.Tab", font=UI_FONT_BOLD, padding=(18, 8))
        style.configure("Title.TLabel", font=TITLE_FONT)
        style.configure("Section.TLabelframe.Label", font=UI_FONT_BOLD)
        style.configure("Result.TLabel", font=RESULT_FONT)
        style.configure("Muted.TLabel", font=("Microsoft YaHei UI", 11), foreground="#666666")

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text=WINDOW_TITLE, style="Title.TLabel").pack(side="left")

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)

        self.enroll_tab = ttk.Frame(notebook, padding=16)
        self.verify_tab = ttk.Frame(notebook, padding=16)
        self.manage_tab = ttk.Frame(notebook, padding=16)
        notebook.add(self.enroll_tab, text="录入建模")
        notebook.add(self.verify_tab, text="身份验证")
        notebook.add(self.manage_tab, text="模板管理")

        self._build_enroll_tab()
        self._build_verify_tab()
        self._build_manage_tab()

    def _build_enroll_tab(self) -> None:
        settings = ttk.LabelFrame(self.enroll_tab, text="录入设置", padding=16, style="Section.TLabelframe")
        settings.pack(fill="x")

        ttk.Label(settings, text="用户名").grid(row=0, column=0, sticky="w", pady=6)
        self.username_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.username_var, width=24, font=UI_FONT).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(settings, text="字符口令").grid(row=0, column=2, sticky="w", padx=(28, 0), pady=6)
        self.phrase_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.phrase_var, width=28, font=UI_FONT).grid(row=0, column=3, sticky="ew", pady=6)

        ttk.Label(settings, text="至少 8 位 ASCII 字符，默认录入 5 次。", style="Muted.TLabel").grid(
            row=1,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(2, 12),
        )

        button_row = ttk.Frame(settings)
        button_row.grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Button(button_row, text="开始录入", command=self.start_enrollment).pack(side="left")
        ttk.Button(button_row, text="保存样本", command=self.save_enrollment_sample).pack(side="left", padx=10)
        ttk.Button(button_row, text="清空", command=self.reset_enrollment_input).pack(side="left")
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        typing_box = ttk.LabelFrame(self.enroll_tab, text="输入样本", padding=16, style="Section.TLabelframe")
        typing_box.pack(fill="x", pady=16)
        self.enroll_progress_var = tk.StringVar(value="尚未开始录入")
        ttk.Label(typing_box, textvariable=self.enroll_progress_var).pack(anchor="w", pady=(0, 10))

        self.enroll_input = ttk.Entry(typing_box, font=INPUT_FONT)
        self.enroll_input.pack(fill="x", ipady=6)
        self.enroll_input.bind("<KeyPress>", self._handle_enroll_key_press)
        self.enroll_input.bind("<KeyRelease>", self._handle_enroll_key_release)

        self.enroll_metrics_var = tk.StringVar(value="等待输入。")
        ttk.Label(typing_box, textvariable=self.enroll_metrics_var, wraplength=1040, justify="left").pack(
            anchor="w",
            pady=(12, 0),
        )

        self.enroll_status_var = tk.StringVar(value="未生成模板。")
        ttk.Label(self.enroll_tab, textvariable=self.enroll_status_var, style="Result.TLabel").pack(anchor="w", pady=(6, 0))

    def _build_verify_tab(self) -> None:
        top = ttk.Frame(self.verify_tab)
        top.pack(fill="x")

        selector = ttk.LabelFrame(top, text="选择模板", padding=16, style="Section.TLabelframe")
        selector.pack(side="left", fill="both", expand=True)
        detail = ttk.LabelFrame(top, text="模板概览", padding=16, style="Section.TLabelframe")
        detail.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ttk.Label(selector, text="用户名").grid(row=0, column=0, sticky="w", pady=6)
        self.verify_user_var = tk.StringVar()
        self.verify_user_combo = ttk.Combobox(selector, textvariable=self.verify_user_var, state="readonly", width=24, font=UI_FONT)
        self.verify_user_combo.grid(row=0, column=1, sticky="ew", pady=6)
        self.verify_user_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_profile_preview())
        ttk.Button(selector, text="刷新", command=self._refresh_profiles).grid(row=0, column=2, padx=(10, 0))
        selector.columnconfigure(1, weight=1)

        self.profile_preview_var = tk.StringVar(value="未选择模板。")
        ttk.Label(detail, textvariable=self.profile_preview_var, wraplength=460, justify="left").pack(anchor="w")

        typing_box = ttk.LabelFrame(self.verify_tab, text="验证输入", padding=16, style="Section.TLabelframe")
        typing_box.pack(fill="x", pady=16)

        self.verify_input = ttk.Entry(typing_box, font=INPUT_FONT)
        self.verify_input.pack(fill="x", ipady=6)
        self.verify_input.bind("<KeyPress>", self._handle_verify_key_press)
        self.verify_input.bind("<KeyRelease>", self._handle_verify_key_release)

        self.verify_metrics_var = tk.StringVar(value="等待验证输入。")
        ttk.Label(typing_box, textvariable=self.verify_metrics_var, wraplength=1040, justify="left").pack(
            anchor="w",
            pady=(12, 0),
        )

        action_row = ttk.Frame(self.verify_tab)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="验证", command=self.run_verification).pack(side="left")
        ttk.Button(action_row, text="清空", command=self.reset_verify_input).pack(side="left", padx=10)

        self.verify_result_var = tk.StringVar(value="尚未执行验证。")
        self.verify_result_label = ttk.Label(self.verify_tab, textvariable=self.verify_result_var, style="Result.TLabel")
        self.verify_result_label.pack(anchor="w", pady=(16, 6))

        self.verify_detail_var = tk.StringVar(value="")
        ttk.Label(self.verify_tab, textvariable=self.verify_detail_var, wraplength=1040, justify="left").pack(anchor="w")

    def _build_manage_tab(self) -> None:
        frame = ttk.LabelFrame(self.manage_tab, text="已保存模板", padding=16, style="Section.TLabelframe")
        frame.pack(fill="both", expand=True)

        self.profile_listbox = tk.Listbox(frame, height=16, font=LIST_FONT)
        self.profile_listbox.pack(fill="both", expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", lambda _event: self._sync_manage_selection())

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x", pady=(12, 0))
        ttk.Button(button_row, text="删除模板", command=self.delete_selected_profile).pack(side="left")
        ttk.Button(button_row, text="刷新", command=self._refresh_profiles).pack(side="left", padx=10)

        self.manage_detail_var = tk.StringVar(value="未选择模板。")
        ttk.Label(frame, textvariable=self.manage_detail_var, wraplength=1040, justify="left").pack(anchor="w", pady=(12, 0))

    def start_enrollment(self) -> None:
        username = self.username_var.get().strip()
        phrase = self.phrase_var.get().strip()
        if not username:
            messagebox.showwarning("缺少用户名", "请先填写用户名。")
            return
        if not phrase or len(phrase) < 8:
            messagebox.showwarning("字符口令过短", "请使用至少 8 位的字符口令。")
            return
        if any(ord(ch) > 127 for ch in phrase):
            messagebox.showwarning("字符范围不支持", "请使用 ASCII 字符，避免输入法影响采集。")
            return

        self.enrollment_samples = []
        self.reset_enrollment_input()
        self.enroll_status_var.set(f"已开始为用户 {username} 录入模板。")
        self.enroll_progress_var.set(f"样本进度：0 / {RECOMMENDED_SAMPLES}")
        self.enroll_input.focus_set()

    def save_enrollment_sample(self) -> None:
        username = self.username_var.get().strip()
        phrase = self.phrase_var.get().strip()
        current_text = self.enroll_input.get()
        if not username or not phrase:
            messagebox.showwarning("信息不完整", "请先填写用户名和字符口令，并点击开始录入。")
            return

        summary = self.enroll_capture.build_summary(current_text)
        if current_text != phrase:
            messagebox.showwarning("字符口令不匹配", "最终输入内容与预设字符口令不一致。")
            return
        if summary.printable_chars < len(phrase):
            messagebox.showwarning("输入不完整", "请完整输入字符口令后再保存样本。")
            return

        self.enrollment_samples.append(summary)
        done = len(self.enrollment_samples)
        self.enroll_progress_var.set(f"样本进度：{done} / {RECOMMENDED_SAMPLES}")
        self.enroll_status_var.set(
            f"样本 {done} 已保存：总时长 {summary.duration:.3f}s，平均按键时长 {summary.avg_dwell:.3f}s。"
        )

        if done >= RECOMMENDED_SAMPLES:
            profile = upsert_profile(username, phrase, self.enrollment_samples, self.storage_path)
            self.enroll_status_var.set(
                f"模板生成完成，阈值 {profile['template']['threshold']}，样本数 {len(profile['samples'])}。"
            )
            self._refresh_profiles()
            messagebox.showinfo("录入完成", f"用户 {username} 的行为口令模板已保存到本地。")
        self.reset_enrollment_input()

    def reset_enrollment_input(self) -> None:
        self.enroll_input.delete(0, tk.END)
        self.enroll_capture.reset()
        self.enroll_metrics_var.set("等待输入。")
        self.enroll_input.focus_set()

    def reset_verify_input(self) -> None:
        self.verify_input.delete(0, tk.END)
        self.verify_capture.reset()
        self.verify_attempt_finished = False
        self.verify_metrics_var.set("等待验证输入。")
        self.verify_result_var.set("尚未执行验证。")
        self.verify_detail_var.set("")
        self.verify_input.focus_set()

    def run_verification(self) -> None:
        username = self.verify_user_var.get().strip()
        profile = get_profile(username, self.storage_path)
        if not profile:
            messagebox.showwarning("未找到模板", "请先选择已存在的用户模板。")
            return

        current_text = self.verify_input.get()
        if not verify_phrase(current_text, profile):
            self.verify_result_var.set("字符口令不匹配")
            self.verify_detail_var.set("字符口令部分未通过，未进入行为特征比对。")
            self.verify_attempt_finished = True
            return

        summary = self.verify_capture.build_summary(current_text)
        result = evaluate_sample(summary, profile["template"])
        self.verify_result_var.set("验证通过" if result["accepted"] else "验证未通过")
        self.verify_detail_var.set(format_explanation(result))
        self.verify_attempt_finished = True

    def delete_selected_profile(self) -> None:
        selection = self.profile_listbox.curselection()
        if not selection:
            messagebox.showwarning("未选择模板", "请先在列表中选择一个模板。")
            return
        username = self.profile_listbox.get(selection[0]).split(" | ", 1)[0]
        if not messagebox.askyesno("确认删除", f"确定删除用户 {username} 的本地模板吗？"):
            return
        delete_profile(username, self.storage_path)
        self._refresh_profiles()

    def load_profile_preview(self) -> None:
        username = self.verify_user_var.get().strip()
        profile = get_profile(username, self.storage_path)
        if not profile:
            self.profile_preview_var.set("未选择模板。")
            return
        template = profile["template"]
        self.profile_preview_var.set(
            f"用户：{username}\n"
            f"样本数：{len(profile['samples'])}\n"
            f"字符口令长度：{profile.get('phrase_length', '未知')}\n"
            f"阈值：{template['threshold']}\n"
            f"平均总时长：{template['mean']['duration']:.3f}s\n"
            f"平均击键速度：{template['mean']['typing_speed']:.2f} keys/s"
        )

    def _refresh_profiles(self) -> None:
        usernames = list_usernames(self.storage_path)
        self.verify_user_combo["values"] = usernames

        self.profile_listbox.delete(0, tk.END)
        for username in usernames:
            profile = get_profile(username, self.storage_path)
            created_at = profile["created_at"].replace("T", " ")
            threshold = profile["template"]["threshold"]
            self.profile_listbox.insert(tk.END, f"{username} | 阈值={threshold} | {created_at}")

        if usernames and not self.verify_user_var.get():
            self.verify_user_var.set(usernames[0])
            self.load_profile_preview()
        elif not usernames:
            self.verify_user_var.set("")
            self.profile_preview_var.set("当前没有已保存模板。")
            self.manage_detail_var.set("当前没有已保存模板。")

    def _sync_manage_selection(self) -> None:
        selection = self.profile_listbox.curselection()
        if not selection:
            return
        username = self.profile_listbox.get(selection[0]).split(" | ", 1)[0]
        profile = get_profile(username, self.storage_path)
        if not profile:
            return

        sample = profile["samples"][0]
        self.manage_detail_var.set(
            f"用户：{username}\n"
            f"保存时间：{profile['created_at'].replace('T', ' ')}\n"
            f"字符口令长度：{profile.get('phrase_length', '未知')}\n"
            f"模板阈值：{profile['template']['threshold']}\n"
            f"首个样本总时长：{sample['duration']:.3f}s，平均按键时长：{sample['avg_dwell']:.3f}s。"
        )

    def _update_live_metrics(self, capture: TypingCapture, text: str, target: tk.StringVar) -> None:
        summary = capture.build_summary(text)
        target.set(
            f"当前统计：字符数 {summary.printable_chars}，总时长 {summary.duration:.3f}s，"
            f"平均按键时长 {summary.avg_dwell:.3f}s，平均击键间隔 {summary.avg_flight:.3f}s，"
            f"纠错次数 {summary.correction_count}。"
        )

    def _handle_enroll_key_press(self, event: tk.Event) -> None:
        self.enroll_capture.on_key_press(event)
        self.root.after_idle(lambda: self._update_live_metrics(self.enroll_capture, self.enroll_input.get(), self.enroll_metrics_var))

    def _handle_enroll_key_release(self, event: tk.Event) -> None:
        self.enroll_capture.on_key_release(event)
        self.root.after_idle(lambda: self._update_live_metrics(self.enroll_capture, self.enroll_input.get(), self.enroll_metrics_var))

    def _handle_verify_key_press(self, event: tk.Event) -> None:
        if self._should_start_new_verify_attempt(event):
            self.verify_input.delete(0, tk.END)
            self.verify_capture.reset()
            self.verify_attempt_finished = False
            self.verify_result_var.set("尚未执行验证。")
            self.verify_detail_var.set("")
        self.verify_capture.on_key_press(event)
        self.root.after_idle(lambda: self._update_live_metrics(self.verify_capture, self.verify_input.get(), self.verify_metrics_var))

    def _handle_verify_key_release(self, event: tk.Event) -> None:
        self.verify_capture.on_key_release(event)
        self.root.after_idle(self._refresh_verify_metrics_after_key)

    def _should_start_new_verify_attempt(self, event: tk.Event) -> bool:
        if event.keysym in TypingCapture.CONTROL_KEYS:
            return False
        if self.verify_attempt_finished:
            return True
        try:
            return (
                self.verify_input.selection_present()
                and self.verify_input.index("sel.first") == 0
                and self.verify_input.index("sel.last") == len(self.verify_input.get())
            )
        except tk.TclError:
            return False

    def _refresh_verify_metrics_after_key(self) -> None:
        if not self.verify_input.get():
            self.verify_capture.reset()
            self.verify_attempt_finished = False
            self.verify_metrics_var.set("等待验证输入。")
            return
        self._update_live_metrics(self.verify_capture, self.verify_input.get(), self.verify_metrics_var)


def monotonic_seconds() -> float:
    import time

    return time.perf_counter()


TypingCapture._clock = staticmethod(monotonic_seconds)


def main() -> None:
    root = tk.Tk()
    app = BehavioralPasswordApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
