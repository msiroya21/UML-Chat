import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def _q(text: str) -> str:
    """Escape double quotes inside a PlantUML quoted label."""
    return str(text).replace('"', '\\"')


def sequence_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'Sequence Flow')}"]

    # Define participants
    participants = ir.get("participants", [])
    for p in participants:
        p_type = p.get("type", "participant")
        p_id = p.get("id")
        p_label = p.get("label", p_id)

        # Valid PlantUML sequence participants types
        if p_type in {"actor", "boundary", "control", "entity", "database", "collections", "queue", "participant"}:
            lines.append(f'{p_type} "{_q(p_label)}" as {p_id}')
        else:
            lines.append(f'participant "{_q(p_label)}" as {p_id}')
            
    lines.append("") # spacer
    
    # Parse messages
    messages = ir.get("messages", [])
    messages_sorted = sorted(messages, key=lambda x: x.get("order", 0))
    
    for msg in messages_sorted:
        sender = msg.get("from")
        receiver = msg.get("to")
        label = msg.get("label", "")
        msg_type = msg.get("type", "sync")
        
        # Arrow types: sync ->, async ->>, return -->
        arrow = "->"
        if msg_type == "async":
            arrow = "->>"
        elif msg_type == "return":
            arrow = "-->"
            
        lines.append(f"{sender} {arrow} {receiver} : {label}")
        
    lines.append("@enduml")
    return "\n".join(lines)

def class_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'Class Model')}"]
    
    # Declare classes
    classes = ir.get("classes", [])
    for c in classes:
        c_id = c.get("id")
        c_name = c.get("name", c_id)
        lines.append(f'class "{_q(c_name)}" as {c_id} {{')
        
        # Class attributes
        attributes = c.get("attributes", [])
        for attr in attributes:
            vis = "+" if attr.get("visibility") == "public" else "-"
            lines.append(f"  {vis}{attr.get('name')}: {attr.get('type')}")
            
        # Class methods
        methods = c.get("methods", [])
        for m in methods:
            vis = "+" if m.get("visibility") == "public" else "-"
            lines.append(f"  {vis}{m.get('name')}() : {m.get('return_type')}")
            
        lines.append("}")
        lines.append("") # spacer
        
    # Declare relationships
    relationships = ir.get("relationships", [])
    for rel in relationships:
        sender = rel.get("from")
        receiver = rel.get("to")
        rel_type = rel.get("type", "association")
        label = rel.get("label", "")
        mult = rel.get("multiplicity")
        
        # Connectors composition: *--, aggregation: o--, inheritance: --|>, association: --
        connector = "--"
        if rel_type == "composition":
            connector = "*--"
        elif rel_type == "aggregation":
            connector = "o--"
        elif rel_type == "inheritance":
            connector = "--|>"
            
        from_mult = f'"{mult.get("from")}" ' if mult and mult.get("from") else ""
        to_mult = f' "{mult.get("to")}"' if mult and mult.get("to") else ""
        
        label_str = f" : {label}" if label else ""
        lines.append(f"{sender} {from_mult}{connector}{to_mult} {receiver}{label_str}")
        
    lines.append("@enduml")
    return "\n".join(lines)

def component_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'Component Architecture')}"]
    
    # Components
    components = ir.get("components", [])
    for c in components:
        c_id = c.get("id")
        c_name = c.get("name", c_id)
        stereo = c.get("stereotype")
        stereo_str = f" <<{stereo}>>" if stereo else ""
        lines.append(f'component "{_q(c_name)}" as {c_id}{stereo_str}')

    lines.append("") # spacer

    # Interfaces
    interfaces = ir.get("interfaces", [])
    for interf in interfaces:
        i_id = interf.get("id")
        i_name = interf.get("name", i_id)
        provided_by = interf.get("provided_by")
        required_by = interf.get("required_by", [])

        lines.append(f'interface "{_q(i_name)}" as {i_id}')
        lines.append(f"{provided_by} -down-|> {i_id} : provides")
        for req in required_by:
            lines.append(f"{req} -( {i_id} : requires")
            
    lines.append("") # spacer
    
    # Dependencies
    dependencies = ir.get("dependencies", [])
    for dep in dependencies:
        sender = dep.get("from")
        receiver = dep.get("to")
        label = dep.get("label", "")
        label_str = f" : {label}" if label else ""
        lines.append(f"{sender} ..> {receiver}{label_str}")
        
    lines.append("@enduml")
    return "\n".join(lines)


def activity_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'Activity Flow')}"]

    nodes = {n.get("id"): n for n in ir.get("nodes", [])}

    def render_ref(node_id: str) -> str:
        node = nodes.get(node_id)
        if not node:
            return f'"{_q(node_id)}"'
        n_type = node.get("type")
        if n_type in {"start", "end"}:
            return "(*)"
        label = node.get("label") or node_id
        return f'"{_q(label)}"'

    for edge in ir.get("edges", []):
        sender = edge.get("from")
        receiver = edge.get("to")
        guard = edge.get("guard")
        guard_str = f"[{guard}]" if guard else ""
        lines.append(f"{render_ref(sender)} -->{guard_str} {render_ref(receiver)}")

    lines.append("@enduml")
    return "\n".join(lines)


def usecase_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", "left to right direction", f"title {ir.get('title', 'Use Cases')}"]

    for actor in ir.get("actors", []):
        a_id = actor.get("id")
        a_name = actor.get("name", a_id)
        lines.append(f'actor "{_q(a_name)}" as {a_id}')

    for uc in ir.get("usecases", []):
        uc_id = uc.get("id")
        uc_name = uc.get("name", uc_id)
        lines.append(f'usecase "{_q(uc_name)}" as {uc_id}')

    lines.append("")

    for rel in ir.get("relationships", []):
        sender = rel.get("from")
        receiver = rel.get("to")
        rel_type = rel.get("type", "association")
        if rel_type == "include":
            lines.append(f"{sender} ..> {receiver} : <<include>>")
        elif rel_type == "extend":
            lines.append(f"{sender} ..> {receiver} : <<extend>>")
        else:
            lines.append(f"{sender} --> {receiver}")

    lines.append("@enduml")
    return "\n".join(lines)


def state_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'State Machine')}"]

    for st in ir.get("states", []):
        s_id = st.get("id")
        s_name = st.get("name", s_id)
        if s_name != s_id:
            lines.append(f'state "{_q(s_name)}" as {s_id}')

    initial = ir.get("initial")
    if initial:
        lines.append(f"[*] --> {initial}")

    for tr in ir.get("transitions", []):
        sender = tr.get("from")
        receiver = tr.get("to")
        label = tr.get("label")
        label_str = f" : {label}" if label else ""
        lines.append(f"{sender} --> {receiver}{label_str}")

    for final in ir.get("finals", []):
        lines.append(f"{final} --> [*]")

    lines.append("@enduml")
    return "\n".join(lines)


def deployment_ir_to_plantuml(ir: Dict[str, Any]) -> str:
    lines = ["@startuml", f"title {ir.get('title', 'Deployment Topology')}"]

    _NODE_KEYWORD = {"node": "node", "database": "database", "cloud": "cloud", "device": "node"}
    for node in ir.get("nodes", []):
        n_id = node.get("id")
        n_name = node.get("name", n_id)
        keyword = _NODE_KEYWORD.get(node.get("type", "node"), "node")
        lines.append(f'{keyword} "{_q(n_name)}" as {n_id}')

    for art in ir.get("artifacts", []):
        a_id = art.get("id")
        a_name = art.get("name", a_id)
        deployed_on = art.get("deployed_on")
        lines.append(f'artifact "{_q(a_name)}" as {a_id}')
        if deployed_on:
            lines.append(f"{deployed_on} .. {a_id}")

    lines.append("")

    for conn in ir.get("connections", []):
        sender = conn.get("from")
        receiver = conn.get("to")
        label = conn.get("label")
        label_str = f" : {label}" if label else ""
        lines.append(f"{sender} --> {receiver}{label_str}")

    lines.append("@enduml")
    return "\n".join(lines)


def ir_to_plantuml(diagram_type: str, ir_dict: Dict[str, Any]) -> str:
    """
    Converts a structured JSON IR into PlantUML DSL code.
    For types without an IR schema the dict carries '_direct_plantuml' and is
    returned as-is.
    """
    if ir_dict.get("_direct_plantuml"):
        return ir_dict["_direct_plantuml"]

    if diagram_type == "sequence":
        return sequence_ir_to_plantuml(ir_dict)
    elif diagram_type == "class":
        return class_ir_to_plantuml(ir_dict)
    elif diagram_type == "component":
        return component_ir_to_plantuml(ir_dict)
    elif diagram_type == "activity":
        return activity_ir_to_plantuml(ir_dict)
    elif diagram_type == "usecase":
        return usecase_ir_to_plantuml(ir_dict)
    elif diagram_type == "state":
        return state_ir_to_plantuml(ir_dict)
    elif diagram_type == "deployment":
        return deployment_ir_to_plantuml(ir_dict)
    else:
        return f"@startuml\ntitle Unknown Diagram Type\n@enduml"
