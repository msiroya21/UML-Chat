from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Optional

# ================= Sequence Diagram IR =================

class Participant(BaseModel):
    id: str
    label: str
    type: str  # e.g., "actor", "component", "database", "boundary", "control", "entity"

class SequenceMessage(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    label: str
    type: str  # e.g., "sync", "async", "return"
    order: int

    class Config:
        populate_by_name = True

class SequenceDiagramIR(BaseModel):
    diagram_type: str = "sequence"
    title: str
    participants: List[Participant]
    messages: List[SequenceMessage]

    @model_validator(mode="after")
    def validate_sequence_semantics(self) -> "SequenceDiagramIR":
        if self.diagram_type != "sequence":
            raise ValueError("diagram_type must be 'sequence'")
        if not self.participants:
            raise ValueError("Participants list cannot be empty")
        
        participant_ids = {p.id for p in self.participants}
        for msg in self.messages:
            if msg.sender not in participant_ids:
                raise ValueError(f"Message sender '{msg.sender}' does not exist in participants")
            if msg.receiver not in participant_ids:
                raise ValueError(f"Message receiver '{msg.receiver}' does not exist in participants")
                
        return self


# ================= Class Diagram IR =================

class ClassAttribute(BaseModel):
    name: str
    type: str
    visibility: str = "public"  # e.g., "public", "private", "protected", "package"

class ClassMethod(BaseModel):
    name: str
    return_type: str
    visibility: str = "public"

class ClassDefinition(BaseModel):
    id: str
    name: str
    attributes: List[ClassAttribute] = Field(default_factory=list)
    methods: List[ClassMethod] = Field(default_factory=list)

class ClassRelationship(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    type: str  # e.g., "composition", "aggregation", "inheritance", "association"
    label: Optional[str] = None
    multiplicity: Optional[Dict[str, str]] = None  # e.g., {"from": "1", "to": "1..*"}

    class Config:
        populate_by_name = True

class ClassDiagramIR(BaseModel):
    diagram_type: str = "class"
    title: str
    classes: List[ClassDefinition]
    relationships: List[ClassRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_class_semantics(self) -> "ClassDiagramIR":
        if self.diagram_type != "class":
            raise ValueError("diagram_type must be 'class'")
        if not self.classes:
            raise ValueError("Classes list cannot be empty")
            
        class_ids = {c.id for c in self.classes}
        for rel in self.relationships:
            if rel.sender not in class_ids:
                raise ValueError(f"Relationship source '{rel.sender}' does not exist in classes")
            if rel.receiver not in class_ids:
                raise ValueError(f"Relationship target '{rel.receiver}' does not exist in classes")
                
        return self


# ================= Component Diagram IR =================

class ComponentDefinition(BaseModel):
    id: str
    name: str
    stereotype: Optional[str] = None  # e.g., "service", "database", "ui"

class InterfaceDefinition(BaseModel):
    id: str
    name: str
    provided_by: str  # Component ID
    required_by: List[str]  # List of Component IDs

class ComponentDependency(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    label: Optional[str] = None

    class Config:
        populate_by_name = True

class ComponentDiagramIR(BaseModel):
    diagram_type: str = "component"
    title: str
    components: List[ComponentDefinition]
    interfaces: List[InterfaceDefinition] = Field(default_factory=list)
    dependencies: List[ComponentDependency] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_component_semantics(self) -> "ComponentDiagramIR":
        if self.diagram_type != "component":
            raise ValueError("diagram_type must be 'component'")
        if not self.components:
            raise ValueError("Components list cannot be empty")
            
        component_ids = {c.id for c in self.components}
        
        for interf in self.interfaces:
            if interf.provided_by not in component_ids:
                raise ValueError(f"Interface provider '{interf.provided_by}' does not exist in components")
            for req in interf.required_by:
                if req not in component_ids:
                    raise ValueError(f"Interface requirer '{req}' does not exist in components")
                    
        for dep in self.dependencies:
            if dep.sender not in component_ids:
                raise ValueError(f"Dependency source '{dep.sender}' does not exist in components")
            if dep.receiver not in component_ids:
                raise ValueError(f"Dependency target '{dep.receiver}' does not exist in components")
                
        return self


# ================= Activity Diagram IR =================

class ActivityNode(BaseModel):
    id: str
    type: str  # "start", "end", "action", "decision", "fork", "join"
    label: str = ""

class ActivityEdge(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    guard: Optional[str] = None  # e.g. condition on a decision branch

    class Config:
        populate_by_name = True

class ActivityDiagramIR(BaseModel):
    diagram_type: str = "activity"
    title: str
    nodes: List[ActivityNode]
    edges: List[ActivityEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_activity_semantics(self) -> "ActivityDiagramIR":
        if self.diagram_type != "activity":
            raise ValueError("diagram_type must be 'activity'")
        if not self.nodes:
            raise ValueError("Nodes list cannot be empty")
        if not any(n.type == "start" for n in self.nodes):
            raise ValueError("Activity diagram must have at least one 'start' node")

        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.sender not in node_ids:
                raise ValueError(f"Edge source '{edge.sender}' does not exist in nodes")
            if edge.receiver not in node_ids:
                raise ValueError(f"Edge target '{edge.receiver}' does not exist in nodes")

        return self


# ================= Use Case Diagram IR =================

class Actor(BaseModel):
    id: str
    name: str

class UseCase(BaseModel):
    id: str
    name: str

class UseCaseRelationship(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    type: str  # "association", "include", "extend"

    class Config:
        populate_by_name = True

class UseCaseDiagramIR(BaseModel):
    diagram_type: str = "usecase"
    title: str
    actors: List[Actor] = Field(default_factory=list)
    usecases: List[UseCase]
    relationships: List[UseCaseRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_usecase_semantics(self) -> "UseCaseDiagramIR":
        if self.diagram_type != "usecase":
            raise ValueError("diagram_type must be 'usecase'")
        if not self.usecases:
            raise ValueError("Use cases list cannot be empty")

        valid_ids = {a.id for a in self.actors} | {u.id for u in self.usecases}
        for rel in self.relationships:
            if rel.sender not in valid_ids:
                raise ValueError(f"Relationship source '{rel.sender}' does not exist")
            if rel.receiver not in valid_ids:
                raise ValueError(f"Relationship target '{rel.receiver}' does not exist")

        return self


# ================= State Machine Diagram IR =================

class State(BaseModel):
    id: str
    name: str

class StateTransition(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    label: Optional[str] = None  # event/guard

    class Config:
        populate_by_name = True

class StateDiagramIR(BaseModel):
    diagram_type: str = "state"
    title: str
    states: List[State]
    transitions: List[StateTransition] = Field(default_factory=list)
    initial: Optional[str] = None  # state id the initial pseudostate points to
    finals: List[str] = Field(default_factory=list)  # state ids that are final

    @model_validator(mode="after")
    def validate_state_semantics(self) -> "StateDiagramIR":
        if self.diagram_type != "state":
            raise ValueError("diagram_type must be 'state'")
        if not self.states:
            raise ValueError("States list cannot be empty")

        # "[*]" is an allowed sentinel for initial/final pseudostates
        state_ids = {s.id for s in self.states} | {"[*]"}
        for tr in self.transitions:
            if tr.sender not in state_ids:
                raise ValueError(f"Transition source '{tr.sender}' does not exist in states")
            if tr.receiver not in state_ids:
                raise ValueError(f"Transition target '{tr.receiver}' does not exist in states")

        if self.initial and self.initial not in state_ids:
            raise ValueError(f"Initial state '{self.initial}' does not exist in states")
        for f in self.finals:
            if f not in state_ids:
                raise ValueError(f"Final state '{f}' does not exist in states")

        return self


# ================= Deployment Diagram IR =================

class DeploymentNode(BaseModel):
    id: str
    name: str
    type: str = "node"  # "node", "database", "cloud", "device"

class Artifact(BaseModel):
    id: str
    name: str
    deployed_on: str  # DeploymentNode id

class DeploymentConnection(BaseModel):
    sender: str = Field(..., alias="from")
    receiver: str = Field(..., alias="to")
    label: Optional[str] = None

    class Config:
        populate_by_name = True

class DeploymentDiagramIR(BaseModel):
    diagram_type: str = "deployment"
    title: str
    nodes: List[DeploymentNode]
    artifacts: List[Artifact] = Field(default_factory=list)
    connections: List[DeploymentConnection] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_deployment_semantics(self) -> "DeploymentDiagramIR":
        if self.diagram_type != "deployment":
            raise ValueError("diagram_type must be 'deployment'")
        if not self.nodes:
            raise ValueError("Nodes list cannot be empty")

        node_ids = {n.id for n in self.nodes}
        for art in self.artifacts:
            if art.deployed_on not in node_ids:
                raise ValueError(f"Artifact '{art.id}' deployed_on '{art.deployed_on}' does not exist in nodes")
        for conn in self.connections:
            if conn.sender not in node_ids:
                raise ValueError(f"Connection source '{conn.sender}' does not exist in nodes")
            if conn.receiver not in node_ids:
                raise ValueError(f"Connection target '{conn.receiver}' does not exist in nodes")

        return self


# ================= Schema Mapping =================

IR_SCHEMA_MAP = {
    "sequence": SequenceDiagramIR,
    "class": ClassDiagramIR,
    "component": ComponentDiagramIR,
    "activity": ActivityDiagramIR,
    "usecase": UseCaseDiagramIR,
    "state": StateDiagramIR,
    "deployment": DeploymentDiagramIR,
}
