import tempfile, subprocess
from llvmlite_artiq import ir as ll, binding as llvm

llvm.initialize()
llvm.initialize_all_targets()
llvm.initialize_all_asmprinters()

class Target:
    """
    A description of the target environment where the binaries
    generaed by the ARTIQ compiler will be deployed.

    :var triple: (string)
        LLVM target triple, e.g. ``"or1k"``
    :var features: (list of string)
        LLVM target CPU features, e.g. ``["mul", "div", "ffl1"]``
    :var print_function: (string)
        Name of a formatted print functions (with the signature of ``printf``)
        provided by the target, e.g. ``"printf"``.
    """
    triple = "unknown"
    features = []
    print_function = "printf"

    def __init__(self):
        self.llcontext = ll.Context()

    def link(self, objects, init_fn):
        """Link the relocatable objects into a shared library for this target."""
        files = []

        def make_tempfile(data=b""):
            f = tempfile.NamedTemporaryFile()
            files.append(f)
            f.write(data)
            f.flush()
            return f

        output_file = make_tempfile()
        cmdline = [self.triple + "-ld", "-shared", "--eh-frame-hdr", "-init", init_fn] + \
                  [make_tempfile(obj).name for obj in objects] + \
                  ["-o", output_file.name]
        linker = subprocess.Popen(cmdline, stderr=subprocess.PIPE)
        stdout, stderr = linker.communicate()
        if linker.returncode != 0:
            raise Exception("Linker invocation failed: " + stderr.decode('utf-8'))

        output = output_file.read()

        for f in files:
            f.close()

        return output

    def compile(self, module):
        """Compile the module to a relocatable object for this target."""
        llmod = module.build_llvm_ir(self)
        llparsedmod = llvm.parse_assembly(str(llmod))
        llparsedmod.verify()

        llpassmgrbuilder = llvm.create_pass_manager_builder()
        llpassmgrbuilder.opt_level  = 2 # -O2
        llpassmgrbuilder.size_level = 1 # -Os

        llpassmgr = llvm.create_module_pass_manager()
        llpassmgrbuilder.populate(llpassmgr)
        llpassmgr.run(llparsedmod)

        lltarget = llvm.Target.from_triple(self.triple)
        llmachine = lltarget.create_target_machine(
                        features=",".join(self.features),
                        reloc="pic", codemodel="default")
        return llmachine.emit_object(llparsedmod)

    def compile_and_link(self, modules):
        return self.link([self.compile(module) for module in modules],
                         init_fn=modules[0].entry_point())

class NativeTarget(Target):
    def __init__(self):
        super().__init__()
        self.triple = llvm.get_default_triple()

class OR1KTarget(Target):
    triple = "or1k-linux"
    attributes = ["mul", "div", "ffl1", "cmov", "addc"]
    print_function = "log"
