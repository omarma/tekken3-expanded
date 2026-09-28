"""Tkinter GUI for Project Studio (stdlib only)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .detect import audit_project
from .models import CheckStatus, MigrateOptions
from .ops import apply_plan
from .plan import build_plan


def run_gui(*, initial_root: Path | None = None) -> int:
    app = ProjectStudioApp(initial_root=initial_root)
    app.mainloop()
    return 0


class ProjectStudioApp(tk.Tk):
    def __init__(self, *, initial_root: Path | None = None) -> None:
        super().__init__()
        self.title("PSXRecomp Project Studio")
        self.geometry("980x720")
        self.minsize(800, 560)

        self.root_var = tk.StringVar(value=str(initial_root) if initial_root else "")
        self.disc_var = tk.StringVar()
        self.players_var = tk.IntVar(value=2)
        self.zip_var = tk.StringVar()
        self.netplay_var = tk.BooleanVar(value=False)
        self.ci_var = tk.BooleanVar(value=True)
        self.probe_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=True)
        self.force_var = tk.BooleanVar(value=False)

        self._report = None
        self._plan = None
        self._step_vars: dict[str, tk.BooleanVar] = {}

        self._build()
        if initial_root:
            self.refresh_audit()

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill=tk.X, **pad)
        ttk.Label(top, text="Game repo:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.root_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(top, text="Browse…", command=self._browse_root).pack(side=tk.LEFT)
        ttk.Button(top, text="Audit", command=self.refresh_audit).pack(side=tk.LEFT, padx=4)

        opts = ttk.LabelFrame(self, text="Options (setup-host only)")
        opts.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(opts)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="Disc .cue (optional probe):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.disc_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(row1, text="Browse…", command=self._browse_disc).pack(side=tk.LEFT)

        row2 = ttk.Frame(opts)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Players:").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=1, to=8, textvariable=self.players_var, width=4).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(row2, text="Zip prefix:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(row2, textvariable=self.zip_var, width=16).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(row2, text="Netplay", variable=self.netplay_var).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Checkbutton(row2, text="CI workflow", variable=self.ci_var).pack(side=tk.LEFT)
        ttk.Checkbutton(row2, text="Probe disc", variable=self.probe_var).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Checkbutton(row2, text="Dry-run", variable=self.dry_run_var).pack(side=tk.LEFT)
        ttk.Checkbutton(row2, text="Force", variable=self.force_var).pack(
            side=tk.LEFT, padx=8
        )

        policy = ttk.Label(
            opts,
            text="Wizard + recomp-ui are always enabled. Releases are setup-host only (no prebuilt game C).",
            foreground="#444",
        )
        policy.pack(anchor=tk.W, padx=8, pady=(0, 6))

        mid = ttk.Panedwindow(self, orient=tk.VERTICAL)
        mid.pack(fill=tk.BOTH, expand=True, **pad)

        audit_frame = ttk.LabelFrame(mid, text="Audit")
        plan_frame = ttk.LabelFrame(mid, text="Plan (uncheck to skip)")
        mid.add(audit_frame, weight=2)
        mid.add(plan_frame, weight=2)

        self.audit_tree = ttk.Treeview(
            audit_frame,
            columns=("status", "severity", "detail"),
            show="tree headings",
            height=12,
        )
        self.audit_tree.heading("#0", text="Check")
        self.audit_tree.heading("status", text="Status")
        self.audit_tree.heading("severity", text="Severity")
        self.audit_tree.heading("detail", text="Detail")
        self.audit_tree.column("#0", width=220)
        self.audit_tree.column("status", width=70, anchor=tk.CENTER)
        self.audit_tree.column("severity", width=100)
        self.audit_tree.column("detail", width=480)
        yscroll = ttk.Scrollbar(audit_frame, orient=tk.VERTICAL, command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=yscroll.set)
        self.audit_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.plan_frame_inner = ttk.Frame(plan_frame)
        self.plan_frame_inner.pack(fill=tk.BOTH, expand=True)
        self.plan_canvas = tk.Canvas(self.plan_frame_inner, highlightthickness=0)
        self.plan_scroll = ttk.Scrollbar(
            self.plan_frame_inner, orient=tk.VERTICAL, command=self.plan_canvas.yview
        )
        self.plan_checks = ttk.Frame(self.plan_canvas)
        self.plan_checks.bind(
            "<Configure>",
            lambda e: self.plan_canvas.configure(scrollregion=self.plan_canvas.bbox("all")),
        )
        self.plan_canvas.create_window((0, 0), window=self.plan_checks, anchor="nw")
        self.plan_canvas.configure(yscrollcommand=self.plan_scroll.set)
        self.plan_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.plan_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, **pad)
        ttk.Button(bottom, text="Build plan", command=self.refresh_plan).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Apply selected", command=self.apply_selected).pack(
            side=tk.LEFT, padx=8
        )
        self.status_var = tk.StringVar(value="Open a game repo and Audit.")
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT, padx=12)

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=False, **pad)
        self.log = tk.Text(log_frame, height=8, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)

    def _browse_root(self) -> None:
        path = filedialog.askdirectory(title="Select game repository root")
        if path:
            self.root_var.set(path)
            self.refresh_audit()

    def _browse_disc(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Redump .cue",
            filetypes=[("Cue sheet", "*.cue"), ("All", "*.*")],
        )
        if path:
            self.disc_var.set(path)
            self.probe_var.set(True)

    def _options(self) -> MigrateOptions:
        return MigrateOptions(
            disc=self.disc_var.get().strip() or None,
            players=int(self.players_var.get()),
            zip_prefix=self.zip_var.get().strip() or None,
            enable_recomp_ui=True,
            enable_wizard=True,
            enable_netplay=bool(self.netplay_var.get()),
            enable_ci=bool(self.ci_var.get()),
            probe_disc=bool(self.probe_var.get()) and bool(self.disc_var.get().strip()),
            record_pins=True,
            dry_run=bool(self.dry_run_var.get()),
            force=bool(self.force_var.get()),
        )

    def _log(self, msg: str) -> None:
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def refresh_audit(self) -> None:
        root_s = self.root_var.get().strip()
        if not root_s:
            messagebox.showerror("Project Studio", "Choose a game repo root.")
            return
        root = Path(root_s).expanduser().resolve()
        if not root.is_dir():
            messagebox.showerror("Project Studio", f"Not a directory:\n{root}")
            return
        self._report = audit_project(root)
        for item in self.audit_tree.get_children():
            self.audit_tree.delete(item)
        for c in self._report.checks:
            self.audit_tree.insert(
                "",
                tk.END,
                text=c.title,
                values=(c.status.value.upper(), c.severity.value, c.detail),
                tags=(c.status.value,),
            )
        self.audit_tree.tag_configure("fail", foreground="#b00020")
        self.audit_tree.tag_configure("warn", foreground="#9a6700")
        self.audit_tree.tag_configure("pass", foreground="#0b6b0b")
        self.status_var.set(
            f"Layout: {self._report.layout.value} · boot={self._report.boot_exe or '?'}"
        )
        self._log(f"Audited {root} → {self._report.layout.value}")
        self.refresh_plan()

    def refresh_plan(self) -> None:
        root_s = self.root_var.get().strip()
        if not root_s:
            return
        root = Path(root_s).expanduser().resolve()
        opts = self._options()
        self._plan = build_plan(root, opts, self._report)
        for child in self.plan_checks.winfo_children():
            child.destroy()
        self._step_vars.clear()
        if not self._plan.steps:
            ttk.Label(self.plan_checks, text="No migration steps needed.").pack(anchor=tk.W)
            return
        for step in self._plan.steps:
            var = tk.BooleanVar(value=step.selected)
            self._step_vars[step.op_id] = var
            row = ttk.Frame(self.plan_checks)
            row.pack(fill=tk.X, anchor=tk.W, pady=2)
            ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            ttk.Label(row, text=f"{step.title}  ({step.op_id})").pack(side=tk.LEFT)
            if step.detail:
                ttk.Label(row, text=step.detail, foreground="#555").pack(
                    side=tk.LEFT, padx=8
                )

    def apply_selected(self) -> None:
        if self._plan is None:
            self.refresh_plan()
        if self._plan is None or not self._plan.steps:
            messagebox.showinfo("Project Studio", "Nothing to apply.")
            return
        opts = self._options()
        opts.enable_wizard = True
        opts.enable_recomp_ui = True
        self._plan.options = opts
        selected = [op for op, var in self._step_vars.items() if var.get()]
        if not selected:
            messagebox.showinfo("Project Studio", "No steps selected.")
            return
        # Sync selected flags onto plan steps
        for step in self._plan.steps:
            step.selected = step.op_id in selected

        mode = "DRY-RUN" if opts.dry_run else "APPLY"
        if not opts.dry_run:
            if not messagebox.askyesno(
                "Project Studio",
                f"Apply {len(selected)} step(s) to:\n{self._plan.root}\n\n"
                "A backup CMakeLists.txt.pre_migrate.bak is written when rewriting CMake.",
            ):
                return

        self._log(f"--- {mode} ({len(selected)} ops) ---")
        results = apply_plan(self._plan, selected=selected)
        failed = 0
        for r in results:
            self._log(f"[{'OK' if r.ok else 'FAIL'}] {r.op_id}: {r.message}")
            for p in r.changed_paths:
                self._log(f"  · {p}")
            if not r.ok:
                failed += 1
        self.status_var.set(f"{mode} done — {failed} failed, {len(results) - failed} ok")
        if not opts.dry_run:
            self.refresh_audit()
        if failed:
            messagebox.showwarning("Project Studio", f"{failed} step(s) failed — see log.")
        else:
            messagebox.showinfo("Project Studio", f"{mode} completed successfully.")
