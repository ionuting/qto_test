"""
Gradio-based IFC Viewer for Google Colab
More robust alternative to ipywidgets that works reliably in Colab.
"""

import gradio as gr
import plotly.graph_objects as go
import pandas as pd
import json
from collections import defaultdict


class GradioIFCViewer:
    """Robust IFC Viewer using Gradio for Google Colab."""
    
    def __init__(self, model, hierarchy, geometry_extractor):
        """
        Initialize the Gradio IFC Viewer.
        
        Parameters:
        -----------
        model : ifcopenshell model
            The loaded IFC model
        hierarchy : dict
            Hierarchical structure {storey: {ifc_type: [elements]}}
        geometry_extractor : GeometryExtractor
            Instance for extracting geometry and colors
        """
        self.model = model
        self.hierarchy = hierarchy
        self.geometry_extractor = geometry_extractor
        
        # Build element data
        self.elements_data = []
        self.element_lookup = {}
        self.mesh_data = {}
        self.original_colors = {}
        self.properties_data = {}
        
        self._build_element_data()
        
    def _build_element_data(self):
        """Build element data for the table and 3D view."""
        for storey_name, types in self.hierarchy.items():
            for ifc_type, elements in types.items():
                for element in elements:
                    mesh_json = self.geometry_extractor.extract_custom_mesh_from_entity(element)
                    if mesh_json:
                        element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                        full_name = f"{storey_name}/{ifc_type}/{element_name}"
                        
                        # Store element reference
                        self.element_lookup[full_name] = element
                        
                        # Parse mesh
                        try:
                            mesh = json.loads(mesh_json) if isinstance(mesh_json, str) else mesh_json
                            self.mesh_data[full_name] = mesh
                        except:
                            continue
                        
                        # Get color
                        color = self.geometry_extractor.get_color_for_element(element) or "#cccccc"
                        self.original_colors[full_name] = color
                        
                        # Extract QTO properties
                        qto_props = self.geometry_extractor.extract_qto_properties(element, self.model)
                        self.properties_data[full_name] = qto_props
                        
                        # Build table row
                        self.elements_data.append({
                            'Storey': storey_name,
                            'Type': ifc_type,
                            'Name': element_name,
                            'FullName': full_name,
                            'GUID': element.GlobalId,
                            **{k: f"{v:.2f}" if isinstance(v, float) else str(v) 
                               for k, v in list(qto_props.items())[:5]}
                        })
    
    def create_3d_figure(self, selected_element=None, visible_elements=None):
        """Create the 3D Plotly figure."""
        fig = go.Figure()
        
        for full_name, mesh in self.mesh_data.items():
            if visible_elements and full_name not in visible_elements:
                continue
                
            vertices = mesh.get('vertices', [])
            faces = mesh.get('faces', [])
            
            if not vertices or not faces:
                continue
            
            # Determine color
            if selected_element and full_name == selected_element:
                color = "yellow"
            else:
                color = self.original_colors.get(full_name, "#cccccc")
            
            # Create mesh
            x = [v[0] for v in vertices]
            y = [v[1] for v in vertices]
            z = [v[2] for v in vertices]
            
            i = [f[0] for f in faces]
            j = [f[1] for f in faces]
            k = [f[2] for f in faces]
            
            fig.add_trace(go.Mesh3d(
                x=x, y=y, z=z,
                i=i, j=j, k=k,
                color=color,
                opacity=1.0,
                flatshading=True,
                name=full_name,
                hoverinfo='name',
                showlegend=False
            ))
        
        # Configure layout
        fig.update_layout(
            scene=dict(
                xaxis=dict(visible=False, showgrid=False),
                yaxis=dict(visible=False, showgrid=False),
                zaxis=dict(visible=False, showgrid=False),
                aspectmode='data',
                bgcolor='rgba(0,0,0,0)'
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='white',
            height=500
        )
        
        return fig
    
    def get_element_properties(self, full_name):
        """Get all properties for an element as a DataFrame."""
        if not full_name or full_name not in self.element_lookup:
            return pd.DataFrame(columns=['PropertySet', 'Property', 'Value', 'Editable'])
        
        element = self.element_lookup[full_name]
        rows = []
        
        if hasattr(element, 'IsDefinedBy'):
            for rel in element.IsDefinedBy:
                if rel.is_a("IfcRelDefinesByProperties"):
                    pset = rel.RelatingPropertyDefinition
                    
                    if pset.is_a("IfcPropertySet") and hasattr(pset, 'HasProperties'):
                        for prop in pset.HasProperties:
                            if hasattr(prop, 'NominalValue'):
                                prop_value = ''
                                if prop.NominalValue and hasattr(prop.NominalValue, 'wrappedValue'):
                                    prop_value = prop.NominalValue.wrappedValue
                                elif prop.NominalValue:
                                    prop_value = str(prop.NominalValue)
                                
                                rows.append({
                                    'PropertySet': pset.Name,
                                    'Property': prop.Name,
                                    'Value': str(prop_value),
                                    'Editable': '✏️'
                                })
                    
                    elif pset.is_a("IfcElementQuantity") and hasattr(pset, 'Quantities'):
                        for qty in pset.Quantities:
                            qty_value = self._get_qty_value(qty)
                            rows.append({
                                'PropertySet': pset.Name,
                                'Property': qty.Name,
                                'Value': f"{qty_value:.4f}" if isinstance(qty_value, float) else str(qty_value),
                                'Editable': '✏️'
                            })
        
        return pd.DataFrame(rows)
    
    @staticmethod
    def _get_qty_value(qty):
        """Extract value from IFC quantity."""
        if qty.is_a('IfcQuantityLength'):
            return getattr(qty, 'LengthValue', None)
        elif qty.is_a('IfcQuantityArea'):
            return getattr(qty, 'AreaValue', None)
        elif qty.is_a('IfcQuantityVolume'):
            return getattr(qty, 'VolumeValue', None)
        elif qty.is_a('IfcQuantityCount'):
            return getattr(qty, 'CountValue', None)
        elif qty.is_a('IfcQuantityWeight'):
            return getattr(qty, 'WeightValue', None)
        return None
    
    def get_elements_table(self, storey_filter="All", type_filter="All"):
        """Get elements table as DataFrame with filters applied."""
        df = pd.DataFrame(self.elements_data)
        
        if storey_filter != "All":
            df = df[df['Storey'] == storey_filter]
        if type_filter != "All":
            df = df[df['Type'] == type_filter]
        
        return df
    
    def get_storey_options(self):
        """Get list of storeys for dropdown."""
        return ["All"] + list(self.hierarchy.keys())
    
    def get_type_options(self):
        """Get list of IFC types for dropdown."""
        types = set()
        for storey_types in self.hierarchy.values():
            types.update(storey_types.keys())
        return ["All"] + sorted(list(types))
    
    def get_element_options(self):
        """Get list of element full names for dropdown."""
        return ["-- Select Element --"] + list(self.element_lookup.keys())
    
    def launch(self):
        """Launch the Gradio interface."""
        
        # State for new properties
        new_properties = []
        
        def update_3d_view(selected_element):
            """Update 3D view with selection highlight."""
            sel = selected_element if selected_element != "-- Select Element --" else None
            return self.create_3d_figure(selected_element=sel)
        
        def update_properties_table(selected_element):
            """Update properties table for selected element."""
            if selected_element == "-- Select Element --":
                return pd.DataFrame(columns=['PropertySet', 'Property', 'Value', 'Editable'])
            return self.get_element_properties(selected_element)
        
        def filter_elements(storey, ifc_type):
            """Filter elements table."""
            df = self.get_elements_table(storey, ifc_type)
            # Return only display columns
            display_cols = ['Storey', 'Type', 'Name', 'GUID']
            return df[display_cols] if not df.empty else pd.DataFrame(columns=display_cols)
        
        def select_from_table(evt: gr.SelectData, elements_df):
            """Handle table row selection."""
            if evt.index[0] < len(elements_df):
                row = elements_df.iloc[evt.index[0]]
                full_name = f"{row['Storey']}/{row['Type']}/{row['Name']}"
                return full_name
            return "-- Select Element --"
        
        def add_new_property(selected_element, pset_name, prop_name, prop_value):
            """Add a new property to the current element."""
            if selected_element == "-- Select Element --":
                return "⚠️ Select an element first", None
            if not pset_name or not prop_name:
                return "⚠️ Fill PropertySet and Property name", None
            
            # Add to IFC model
            element = self.element_lookup.get(selected_element)
            if not element:
                return "⚠️ Element not found", None
            
            try:
                # Find or create PropertySet
                pset = None
                if hasattr(element, 'IsDefinedBy'):
                    for rel in element.IsDefinedBy:
                        if rel.is_a("IfcRelDefinesByProperties"):
                            if rel.RelatingPropertyDefinition.Name == pset_name:
                                pset = rel.RelatingPropertyDefinition
                                break
                
                if pset is None:
                    # Create new PropertySet
                    owner_history = self.model.by_type("IfcOwnerHistory")[0] if self.model.by_type("IfcOwnerHistory") else None
                    pset = self.model.create_entity(
                        "IfcPropertySet",
                        GlobalId=self.model.create_guid(),
                        OwnerHistory=owner_history,
                        Name=pset_name,
                        HasProperties=[]
                    )
                    self.model.create_entity(
                        "IfcRelDefinesByProperties",
                        GlobalId=self.model.create_guid(),
                        OwnerHistory=owner_history,
                        RelatedObjects=[element],
                        RelatingPropertyDefinition=pset
                    )
                
                # Create property
                new_prop = self.model.create_entity(
                    "IfcPropertySingleValue",
                    Name=prop_name,
                    NominalValue=self.model.create_entity("IfcText", prop_value)
                )
                
                # Add to PropertySet
                if hasattr(pset, 'HasProperties'):
                    props = list(pset.HasProperties) if pset.HasProperties else []
                    props.append(new_prop)
                    pset.HasProperties = props
                
                # Update table
                new_df = self.get_element_properties(selected_element)
                return f"✅ Added {pset_name}/{prop_name} = {prop_value}", new_df
                
            except Exception as e:
                return f"❌ Error: {str(e)}", None
        
        def save_ifc_file(filename):
            """Save modified IFC file."""
            try:
                if not filename.endswith('.ifc'):
                    filename += '.ifc'
                self.model.write(filename)
                return f"✅ Saved to {filename}"
            except Exception as e:
                return f"❌ Error saving: {str(e)}"
        
        # Build Gradio interface
        with gr.Blocks(title="IFC Viewer", theme=gr.themes.Soft()) as demo:
            gr.Markdown("# 🏗️ IFC Model Viewer - Interactive 3D with Editable Properties")
            
            # Store current elements table as state
            elements_state = gr.State(pd.DataFrame(self.elements_data))
            
            with gr.Row():
                # Left column: 3D View and filters
                with gr.Column(scale=2):
                    gr.Markdown("### 📊 3D Model View")
                    plot_3d = gr.Plot(value=self.create_3d_figure(), label="3D View")
                    
                    gr.Markdown("### 🔍 Filters")
                    with gr.Row():
                        storey_dropdown = gr.Dropdown(
                            choices=self.get_storey_options(),
                            value="All",
                            label="Filter by Storey"
                        )
                        type_dropdown = gr.Dropdown(
                            choices=self.get_type_options(),
                            value="All",
                            label="Filter by IFC Type"
                        )
                    
                    gr.Markdown("### 🎯 Select Element")
                    element_dropdown = gr.Dropdown(
                        choices=self.get_element_options(),
                        value="-- Select Element --",
                        label="Select Element (or click table row)"
                    )
                    
                    gr.Markdown("### 📋 Elements Table (click to select)")
                    elements_table = gr.Dataframe(
                        value=self.get_elements_table()[['Storey', 'Type', 'Name', 'GUID']],
                        label="Elements",
                        interactive=False,
                        height=200
                    )
                
                # Right column: Properties
                with gr.Column(scale=1):
                    gr.Markdown("### ✏️ Element Properties")
                    properties_table = gr.Dataframe(
                        value=pd.DataFrame(columns=['PropertySet', 'Property', 'Value', 'Editable']),
                        label="Properties",
                        interactive=False,
                        height=300
                    )
                    
                    gr.Markdown("### ➕ Add New Property")
                    new_pset = gr.Textbox(label="PropertySet Name", placeholder="e.g., Pset_Custom")
                    new_prop_name = gr.Textbox(label="Property Name", placeholder="e.g., Material")
                    new_prop_value = gr.Textbox(label="Value", placeholder="e.g., Concrete")
                    add_btn = gr.Button("➕ Add Property", variant="primary")
                    status_text = gr.Textbox(label="Status", interactive=False)
                    
                    gr.Markdown("### 💾 Save Model")
                    save_filename = gr.Textbox(label="Filename", value="modified_model.ifc")
                    save_btn = gr.Button("💾 Save IFC File", variant="secondary")
                    save_status = gr.Textbox(label="Save Status", interactive=False)
            
            # Event handlers
            element_dropdown.change(
                fn=update_3d_view,
                inputs=[element_dropdown],
                outputs=[plot_3d]
            )
            
            element_dropdown.change(
                fn=update_properties_table,
                inputs=[element_dropdown],
                outputs=[properties_table]
            )
            
            storey_dropdown.change(
                fn=filter_elements,
                inputs=[storey_dropdown, type_dropdown],
                outputs=[elements_table]
            )
            
            type_dropdown.change(
                fn=filter_elements,
                inputs=[storey_dropdown, type_dropdown],
                outputs=[elements_table]
            )
            
            # Table selection -> update dropdown
            elements_table.select(
                fn=lambda evt, df: (
                    f"{df.iloc[evt.index[0]]['Storey']}/{df.iloc[evt.index[0]]['Type']}/{df.iloc[evt.index[0]]['Name']}"
                    if evt.index[0] < len(df) else "-- Select Element --"
                ),
                inputs=[elements_state],
                outputs=[element_dropdown]
            )
            
            add_btn.click(
                fn=add_new_property,
                inputs=[element_dropdown, new_pset, new_prop_name, new_prop_value],
                outputs=[status_text, properties_table]
            )
            
            save_btn.click(
                fn=save_ifc_file,
                inputs=[save_filename],
                outputs=[save_status]
            )
        
        return demo


def visualize_ifc_gradio(ifc_source, color_config_path=None, share=False):
    """
    Visualize IFC model using Gradio (robust for Google Colab).
    
    Parameters:
    -----------
    ifc_source : str
        Path or URL to IFC file
    color_config_path : str, optional
        Path to YAML color configuration
    share : bool
        If True, creates a public shareable link (useful for Colab)
    
    Returns:
    --------
    Gradio Blocks interface
    """
    from .ifc_viewer_loader import IFCDownloader
    from .ifc_viewer_geometry import GeometryExtractor
    from .ifc_viewer_hierarchy import HierarchicalStructure
    from pathlib import Path
    
    print("🚀 Loading IFC model...")
    model = IFCDownloader.download_and_load(ifc_source)
    
    print("📊 Building hierarchy...")
    hierarchy_builder = HierarchicalStructure(model)
    hierarchy = hierarchy_builder.get_hierarchy()
    
    # Get color config
    if color_config_path is None:
        package_dir = Path(__file__).parent
        color_config_path = package_dir / "configs" / "default_colors.yaml"
        if not color_config_path.exists():
            color_config_path = None
    
    print("🎨 Initializing geometry extractor...")
    geometry_extractor = GeometryExtractor(color_config_path)
    
    print("🔧 Building Gradio interface...")
    viewer = GradioIFCViewer(model, hierarchy, geometry_extractor)
    demo = viewer.launch()
    
    print("✅ Launching viewer...")
    demo.launch(share=share, inline=True)
    
    return demo
