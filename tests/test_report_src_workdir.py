"""D-ARTIFACT-SUBDIR: report_src must follow the execution workdir —
a framework running in a subdirectory (bruno executes from the
collection root) writes Reports there; uploading src/Reports collected
nothing and the run was falsely INCOMPLETE with zero artifacts."""


def test_report_src_follows_workdir():
    class _Ex:
        def run_config(self):
            return {}

        def snapshot(self):
            return {"run_config": {}}

    from testorchestrator.buildbot_cfg import node_exec_spec
    # default: no override — src/Reports
    spec = node_exec_spec(_Ex(), "npx", ["jest"])
    assert spec["report_src"] == "src/Reports"
    # bruno-style subdirectory override — reports land in the subdir
    spec = node_exec_spec(_Ex(), "/usr/local/bin/bru", ["run"],
                          workdir="build/src/bruno")
    assert spec["report_src"] == "src/bruno/Reports", spec["report_src"]
    # deeper nesting (monorepo collection root)
    spec = node_exec_spec(_Ex(), "npx", ["jest"],
                          workdir="build/src/services/gamma")
    assert spec["report_src"] == "src/services/gamma/Reports"
