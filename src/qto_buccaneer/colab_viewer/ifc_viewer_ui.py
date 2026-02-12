"""
Interactive UI Module for IFC Viewer
Provides hierarchical tables, filters, interactive controls, editable property panels,
and IFC save functionality for IFC model visualization.
"""

import ipywidgets as widgets
from IPython.display import display
import plotly.graph_objects as go
from collections import defaultdict
from .ifc_viewer_geometry import GeometryExtractor


class HierarchicalTableUI:
    """
    Creates an interactive UI with filters, hierarchical table, visibility controls,
    editable property panels, and IFC write-back for model visualization.
    
    Features:
    - Click on 3D mesh to select element
    - Editable properties table for selected element
    - Add new properties to elements
    - Save modified/new properties back to IFC model
    - Export modified IFC to file
    """
    
    def __init__(self, hierarchy, visualizer, model):
        """
        Initialize the UI with hierarchy data, visualizer, and IFC model.
        
        Parameters:
        -----------
        hierarchy : dict
            Hierarchical structure of IFC elements (storey -> type -> elements)
        visualizer : Visualizer3D
            The 3D visualizer instance (FigureWidget-based)
        model : ifcopenshell.file
            The loaded IFC model
        """
        self.hierarchy = hierarchy
        self.visualizer = visualizer
        self.model = model
        self.all_checkboxes = {}
        self.table_output = widgets.Output()
        self.filter_storey = None
        self.filter_ifc_type = None
        
        # Editable properties state
        self.current_selected_element = None
        self.current_selected_full_name = None
        self.properties_widgets = {}  # (pset_name, prop_name) -> Text widget
        self.editable_props_container = widgets.VBox(
            layout=widgets.Layout(
                border='1px solid #ddd',
                padding='10px',
                max_height='700px',
                overflow_y='auto',
                min_width='480px'
            )
        )
        self.save_status = widgets.HTML(value="")
        self.new_props_container = widgets.VBox()
        
        # Element selector dropdown
        self.element_selector = widgets.Dropdown(
            description='Element:',
            layout=widgets.Layout(width='400px')
        )
        self.element_selector.observe(self._on_element_dropdown_change, names='value')
        
        # Build element lookup
        self.element_lookup = {}
        self._build_element_lookup()

    def _build_element_lookup(self):
        """Build lookup dict from full_name to IFC element."""
        for storey_name, types in self.hierarchy.items():
            for ifc_type, elements in types.items():
                for element in elements:
                    element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                    full_name = f"{storey_name}/{ifc_type}/{element_name}"
                    self.element_lookup[full_name] = element

    def create_ui(self):
        """
        Create and return the complete UI widget with all controls.
        
        Returns:
        --------
        widgets.VBox
            The complete UI widget
        """
        print("🔧 Starting UI creation with 3D click selection and editable properties...")
        
        # Create filter dropdowns
        storey_options = ['All'] + sorted(list(self.hierarchy.keys()))
        ifc_type_options = ['All'] + sorted(set(
            ifc_type for storey in self.hierarchy.values() for ifc_type in storey.keys()
        ))
        
        self.storey_dropdown = widgets.Dropdown(
            options=storey_options,
            value='All',
            description='Storey:',
            layout=widgets.Layout(width='300px')
        )
        
        self.ifc_type_dropdown = widgets.Dropdown(
            options=ifc_type_options,
            value='All',
            description='IFC Type:',
            layout=widgets.Layout(width='300px')
        )
        
        apply_filter_btn = widgets.Button(
            description='Apply Filters',
            button_style='success',
            layout=widgets.Layout(width='120px')
        )
        apply_filter_btn.on_click(self._apply_filters)
        
        filter_box = widgets.HBox([self.storey_dropdown, self.ifc_type_dropdown, apply_filter_btn])
        
        # Element selector dropdown (populated from visible elements)
        self._update_element_selector()
        
        # Create visibility accordion
        visibility_accordion = self._create_visibility_accordion()
        
        # Expand/collapse buttons
        expand_all_btn = widgets.Button(
            description="Expand all",
            button_style='info',
            layout=widgets.Layout(width='120px')
        )
        collapse_all_btn = widgets.Button(
            description="Collapse all",
            button_style='info',
            layout=widgets.Layout(width='120px')
        )
        
        expand_all_btn.on_click(lambda x: self._expand_all_accordions(visibility_accordion))
        collapse_all_btn.on_click(lambda x: self._collapse_all_accordions(visibility_accordion))
        
        buttons_box = widgets.HBox([expand_all_btn, collapse_all_btn])
        
        # Visibility panel
        visibility_panel = widgets.VBox([
            widgets.HTML("<b>🎛️ Element Visibility Control</b>"),
            buttons_box,
            visibility_accordion
        ], layout=widgets.Layout(
            border='1px solid #ddd',
            padding='10px',
            max_height='400px',
            overflow_y='auto'
        ))
        
        # Initial empty editable properties panel
        self.editable_props_container.children = [
            widgets.HTML(
                "<b>📋 Element Properties (Editable):</b><br>"
                "<i>Click on an element in the 3D view or select from the dropdown to edit its properties</i>"
            )
        ]
        
        # Attach 3D click handlers (only works with FigureWidget)
        self.visualizer.attach_click_handlers(self._on_3d_click)
        
        # Left panel: 3D view, filters, table, visibility
        left_panel = widgets.VBox([
            widgets.HTML("<b>📊 IFC Elements - Filters & 3D View</b>"),
            filter_box,
            widgets.HTML("<small>💡 Click on an element in the 3D view to select it, or use the dropdown below</small>"),
            self.visualizer.fig,  # FigureWidget embedded directly
            widgets.HBox([
                widgets.HTML("<b>🔍 Select Element:</b> "),
                self.element_selector
            ]),
            self.table_output,
            visibility_panel
        ])
        
        # Right panel: editable properties
        right_panel = widgets.VBox([
            self.editable_props_container
        ], layout=widgets.Layout(min_width='500px'))
        
        # Main layout - side by side
        main_layout = widgets.HBox([left_panel, right_panel])
        
        # Initial update
        self._update_table()
        
        print(f"✅ UI created with 3D click selection, editable properties, and save to IFC")
        return main_layout

    # -------------------------------------------------------------------------
    # 3D Click & Element Selection
    # -------------------------------------------------------------------------
    
    def _on_3d_click(self, trace, points, selector):
        """Handle click on 3D mesh element."""
        if points.point_inds:
            full_name = trace.name
            if full_name in self.visualizer.mesh_dict:
                # Update dropdown without triggering observer
                self.element_selector.unobserve(self._on_element_dropdown_change, names='value')
                if full_name in [opt for opt in self.element_selector.options]:
                    self.element_selector.value = full_name
                self.element_selector.observe(self._on_element_dropdown_change, names='value')
                self._select_mesh(full_name)
    
    def _on_element_dropdown_change(self, change):
        """Handle element selection from dropdown."""
        full_name = change['new']
        if full_name and full_name in self.visualizer.mesh_dict:
            self._select_mesh(full_name)
    
    def _update_element_selector(self):
        """Update element selector dropdown with visible elements."""
        visible_elements = []
        for storey_name, types in self.hierarchy.items():
            if self.filter_storey and self.filter_storey != 'All' and storey_name != self.filter_storey:
                continue
            for ifc_type, elements in types.items():
                if self.filter_ifc_type and self.filter_ifc_type != 'All' and ifc_type != self.filter_ifc_type:
                    continue
                for element in elements:
                    if GeometryExtractor.extract_custom_mesh_from_entity(element):
                        element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                        full_name = f"{storey_name}/{ifc_type}/{element_name}"
                        if full_name in self.visualizer.mesh_dict:
                            visible_elements.append(full_name)
        
        self.element_selector.unobserve(self._on_element_dropdown_change, names='value')
        self.element_selector.options = [''] + sorted(visible_elements)
        self.element_selector.value = ''
        self.element_selector.observe(self._on_element_dropdown_change, names='value')

    def _select_mesh(self, full_name):
        """Select and highlight a mesh, showing editable properties."""
        if full_name not in self.visualizer.mesh_dict:
            return
        
        self.visualizer.selected_mesh[0] = full_name
        
        # Highlight selected mesh in yellow using batch_update for efficiency
        if self.visualizer._is_figure_widget:
            with self.visualizer.fig.batch_update():
                for trace in self.visualizer.fig.data:
                    color = "#ffff00" if trace.name == full_name else self.visualizer.original_colors.get(trace.name, "#cccccc")
                    trace.color = color
        else:
            for i, trace in enumerate(self.visualizer.fig.data):
                color = "#ffff00" if trace.name == full_name else self.visualizer.original_colors.get(trace.name, "#cccccc")
                self.visualizer.fig.data[i].color = color
            self._update_viewer()
        
        # Show editable properties for this element
        self._show_editable_properties(full_name)

    def _deselect_current(self):
        """Deselect the currently selected mesh."""
        self.visualizer.selected_mesh[0] = None
        
        if self.visualizer._is_figure_widget:
            with self.visualizer.fig.batch_update():
                for trace in self.visualizer.fig.data:
                    trace.color = self.visualizer.original_colors.get(trace.name, "#cccccc")
        else:
            for i, trace in enumerate(self.visualizer.fig.data):
                self.visualizer.fig.data[i].color = self.visualizer.original_colors.get(trace.name, "#cccccc")
            self._update_viewer()
        
        self.editable_props_container.children = [
            widgets.HTML("<b>📋 Element Properties:</b><br><i>No element selected</i>")
        ]

    # -------------------------------------------------------------------------
    # Editable Properties Panel
    # -------------------------------------------------------------------------
    
    def _show_editable_properties(self, full_name):
        """Create editable property widgets for the selected element."""
        element = self.element_lookup.get(full_name) or self.visualizer.element_map.get(full_name)
        if not element:
            self.editable_props_container.children = [
                widgets.HTML(f"<b>⚠️ Element not found for: {full_name}</b>")
            ]
            return
        
        self.current_selected_element = element
        self.current_selected_full_name = full_name
        self.properties_widgets.clear()
        
        rows = []
        
        # Header with element info
        element_name = element.Name or element.GlobalId
        rows.append(widgets.HTML(
            f"<h4 style='margin:5px 0'>📋 Properties: {element_name}</h4>"
            f"<small><b>GUID:</b> {element.GlobalId} | <b>Type:</b> {element.is_a()}</small><hr>"
        ))
        
        # Column headers
        header_row = widgets.HBox([
            widgets.HTML("<b style='min-width:160px; display:inline-block'>PropertySet</b>"),
            widgets.HTML("<b style='min-width:180px; display:inline-block'>Property</b>"),
            widgets.HTML("<b style='min-width:200px; display:inline-block'>Value</b>"),
        ])
        rows.append(header_row)
        
        # Collect properties from all PropertySets and ElementQuantities
        if hasattr(element, 'IsDefinedBy'):
            for rel in element.IsDefinedBy:
                if rel.is_a("IfcRelDefinesByProperties"):
                    pset = rel.RelatingPropertyDefinition
                    
                    # IfcPropertySet (regular properties)
                    if pset.is_a("IfcPropertySet") and hasattr(pset, 'HasProperties'):
                        rows.append(widgets.HTML(
                            f"<hr><b style='color:#4CAF50'>📁 {pset.Name}</b>"
                        ))
                        for prop in pset.HasProperties:
                            if hasattr(prop, 'NominalValue'):
                                prop_name = getattr(prop, 'Name', 'Unknown')
                                prop_value = ''
                                if prop.NominalValue and hasattr(prop.NominalValue, 'wrappedValue'):
                                    prop_value = prop.NominalValue.wrappedValue
                                elif prop.NominalValue:
                                    prop_value = str(prop.NominalValue)
                                
                                value_widget = widgets.Text(
                                    value=str(prop_value),
                                    layout=widgets.Layout(width='200px')
                                )
                                
                                row = widgets.HBox([
                                    widgets.Label(value=pset.Name, layout=widgets.Layout(width='160px')),
                                    widgets.Label(value=prop_name, layout=widgets.Layout(width='180px')),
                                    value_widget
                                ])
                                rows.append(row)
                                self.properties_widgets[(pset.Name, prop_name)] = value_widget
                    
                    # IfcElementQuantity (QTO quantities)
                    elif pset.is_a("IfcElementQuantity") and hasattr(pset, 'Quantities'):
                        rows.append(widgets.HTML(
                            f"<hr><b style='color:#2196F3'>📐 {pset.Name}</b>"
                        ))
                        for qty in pset.Quantities:
                            qty_name = getattr(qty, 'Name', 'Unknown')
                            qty_value = self._get_qty_value(qty)
                            
                            value_widget = widgets.Text(
                                value=str(qty_value) if qty_value is not None else '',
                                layout=widgets.Layout(width='200px')
                            )
                            
                            row = widgets.HBox([
                                widgets.Label(value=pset.Name, layout=widgets.Layout(width='160px')),
                                widgets.Label(value=qty_name, layout=widgets.Layout(width='180px')),
                                value_widget
                            ])
                            rows.append(row)
                            self.properties_widgets[(pset.Name, qty_name)] = value_widget
        
        # IfcCovering properties for walls
        if element.is_a("IfcWall") or element.is_a("IfcWallStandardCase"):
            try:
                for rel in self.model.by_type("IfcRelCoversBldgElements"):
                    if rel.RelatingBuildingElement == element and rel.RelatedCoverings:
                        for covering in rel.RelatedCoverings:
                            if GeometryExtractor.extract_custom_mesh_from_entity(covering):
                                cov_label = f"Covering_{covering.GlobalId[:8]}"
                                rows.append(widgets.HTML(
                                    f"<hr><b style='color:#FF9800'>🧱 IfcCovering: {cov_label}</b>"
                                ))
                                if hasattr(covering, 'IsDefinedBy'):
                                    for rel_cov in covering.IsDefinedBy:
                                        if rel_cov.is_a("IfcRelDefinesByProperties"):
                                            pset_cov = rel_cov.RelatingPropertyDefinition
                                            if pset_cov.is_a("IfcElementQuantity") and hasattr(pset_cov, 'Quantities'):
                                                for qty in pset_cov.Quantities:
                                                    qty_name = getattr(qty, 'Name', 'Unknown')
                                                    qty_value = self._get_qty_value(qty)
                                                    row = widgets.HBox([
                                                        widgets.Label(
                                                            value=f"{pset_cov.Name} (Cov)",
                                                            layout=widgets.Layout(width='160px')
                                                        ),
                                                        widgets.Label(
                                                            value=qty_name,
                                                            layout=widgets.Layout(width='180px')
                                                        ),
                                                        widgets.Label(
                                                            value=str(qty_value) if qty_value is not None else 'N/A',
                                                            layout=widgets.Layout(width='200px')
                                                        )
                                                    ])
                                                    rows.append(row)
            except Exception:
                pass
        
        # ---- Add New Property Section ----
        rows.append(widgets.HTML("<hr><b>➕ Add New Property:</b>"))
        
        self.new_pset_input = widgets.Text(
            placeholder="PropertySet (e.g., Pset_Custom)",
            layout=widgets.Layout(width='200px')
        )
        self.new_prop_name_input = widgets.Text(
            placeholder="Property name",
            layout=widgets.Layout(width='180px')
        )
        self.new_prop_value_input = widgets.Text(
            placeholder="Value",
            layout=widgets.Layout(width='200px')
        )
        add_btn = widgets.Button(
            description="➕ Add",
            button_style='info',
            layout=widgets.Layout(width='80px')
        )
        add_btn.on_click(self._add_new_property_row)
        
        new_prop_row = widgets.HBox([
            self.new_pset_input,
            self.new_prop_name_input,
            self.new_prop_value_input,
            add_btn
        ])
        rows.append(new_prop_row)
        
        # Container for dynamically added new properties
        self.new_props_container = widgets.VBox()
        rows.append(self.new_props_container)
        
        # ---- Save Buttons ----
        rows.append(widgets.HTML("<hr>"))
        
        save_model_btn = widgets.Button(
            description="💾 Save to IFC Model",
            button_style='success',
            layout=widgets.Layout(width='200px'),
            tooltip="Save modified and new properties to the in-memory IFC model"
        )
        save_model_btn.on_click(self._save_properties_to_ifc)
        
        self.save_file_name = widgets.Text(
            value="modified_model.ifc",
            placeholder="Output filename",
            layout=widgets.Layout(width='200px')
        )
        save_file_btn = widgets.Button(
            description="💾 Save IFC File",
            button_style='warning',
            layout=widgets.Layout(width='150px'),
            tooltip="Save the IFC model to a file (and download in Colab)"
        )
        save_file_btn.on_click(self._save_ifc_to_file)
        
        self.save_status = widgets.HTML(value="")
        
        rows.append(widgets.HBox([save_model_btn]))
        rows.append(widgets.HBox([
            widgets.HTML("<b>Export:</b> "),
            self.save_file_name,
            save_file_btn
        ]))
        rows.append(self.save_status)
        
        self.editable_props_container.children = rows

    # -------------------------------------------------------------------------
    # Property Helpers
    # -------------------------------------------------------------------------
    
    @staticmethod
    def _get_qty_value(qty):
        """Extract value from an IFC quantity."""
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

    def _add_new_property_row(self, b):
        """Add a new property entry to the editable list."""
        pset_name = self.new_pset_input.value.strip()
        prop_name = self.new_prop_name_input.value.strip()
        prop_value = self.new_prop_value_input.value.strip()
        
        if not pset_name or not prop_name:
            self.save_status.value = (
                "<span style='color:orange'>⚠️ Please fill in both PropertySet name and Property name</span>"
            )
            return
        
        # Check for duplicates
        if (pset_name, prop_name) in self.properties_widgets:
            self.save_status.value = (
                f"<span style='color:orange'>⚠️ Property {pset_name}/{prop_name} already exists — "
                f"edit its value above</span>"
            )
            return
        
        # Create editable row
        value_widget = widgets.Text(value=prop_value, layout=widgets.Layout(width='200px'))
        self.properties_widgets[(pset_name, prop_name)] = value_widget
        
        new_row = widgets.HBox([
            widgets.Label(value=pset_name, layout=widgets.Layout(width='160px')),
            widgets.Label(value=prop_name, layout=widgets.Layout(width='180px')),
            value_widget,
            widgets.HTML("<span style='color:green; margin-left:5px'>✨ New</span>")
        ])
        
        # Add to new props container
        current_children = list(self.new_props_container.children)
        current_children.append(new_row)
        self.new_props_container.children = current_children
        
        # Clear inputs
        self.new_pset_input.value = ""
        self.new_prop_name_input.value = ""
        self.new_prop_value_input.value = ""
        
        self.save_status.value = (
            f"<span style='color:green'>✅ Added property <b>{pset_name}/{prop_name}</b> "
            f"— click <b>Save to IFC Model</b> to persist</span>"
        )

    # -------------------------------------------------------------------------
    # Save to IFC
    # -------------------------------------------------------------------------
    
    def _save_properties_to_ifc(self, b):
        """Save all modified and new properties to the IFC model in memory."""
        if not self.current_selected_element:
            self.save_status.value = "<span style='color:orange'>⚠️ No element selected</span>"
            return
        
        element = self.current_selected_element
        
        try:
            import ifcopenshell
            import ifcopenshell.guid
            
            # Group all property widgets by PropertySet name
            changes_by_pset = defaultdict(dict)
            for (pset_name, prop_name), widget in self.properties_widgets.items():
                changes_by_pset[pset_name][prop_name] = widget.value
            
            modified_count = 0
            added_count = 0
            
            for pset_name, props in changes_by_pset.items():
                # Try to find an existing PropertySet or ElementQuantity
                existing_pset = None
                if hasattr(element, 'IsDefinedBy'):
                    for rel in element.IsDefinedBy:
                        if rel.is_a("IfcRelDefinesByProperties"):
                            pdef = rel.RelatingPropertyDefinition
                            if hasattr(pdef, 'Name') and pdef.Name == pset_name:
                                existing_pset = pdef
                                break
                
                if existing_pset:
                    if existing_pset.is_a("IfcPropertySet"):
                        # Update existing PropertySet
                        existing_prop_dict = {}
                        if hasattr(existing_pset, 'HasProperties'):
                            existing_prop_dict = {
                                p.Name: p for p in existing_pset.HasProperties if hasattr(p, 'Name')
                            }
                        new_props_list = list(existing_pset.HasProperties) if hasattr(existing_pset, 'HasProperties') else []
                        
                        for prop_name, new_value_str in props.items():
                            if prop_name in existing_prop_dict:
                                # Update existing property
                                prop = existing_prop_dict[prop_name]
                                if hasattr(prop, 'NominalValue') and prop.NominalValue:
                                    old_type = prop.NominalValue.is_a()
                                    new_wrapped = self._create_ifc_value_by_type(old_type, new_value_str)
                                    if new_wrapped is not None:
                                        prop.NominalValue = new_wrapped
                                        modified_count += 1
                                else:
                                    prop.NominalValue = self.model.createIfcText(new_value_str)
                                    modified_count += 1
                            else:
                                # Add new property to existing PropertySet
                                new_value = self.model.createIfcText(new_value_str)
                                new_prop = self.model.createIfcPropertySingleValue(
                                    prop_name, None, new_value, None
                                )
                                new_props_list.append(new_prop)
                                added_count += 1
                        
                        existing_pset.HasProperties = tuple(new_props_list)
                    
                    elif existing_pset.is_a("IfcElementQuantity"):
                        # Update existing ElementQuantity values
                        existing_qty_dict = {}
                        if hasattr(existing_pset, 'Quantities'):
                            existing_qty_dict = {
                                q.Name: q for q in existing_pset.Quantities if hasattr(q, 'Name')
                            }
                        
                        for prop_name, new_value_str in props.items():
                            if prop_name in existing_qty_dict:
                                qty = existing_qty_dict[prop_name]
                                try:
                                    new_val = float(new_value_str)
                                    if qty.is_a('IfcQuantityLength'):
                                        qty.LengthValue = new_val
                                    elif qty.is_a('IfcQuantityArea'):
                                        qty.AreaValue = new_val
                                    elif qty.is_a('IfcQuantityVolume'):
                                        qty.VolumeValue = new_val
                                    elif qty.is_a('IfcQuantityCount'):
                                        qty.CountValue = new_val
                                    elif qty.is_a('IfcQuantityWeight'):
                                        qty.WeightValue = new_val
                                    modified_count += 1
                                except ValueError:
                                    pass  # Skip non-numeric values for quantities
                else:
                    # Create a brand-new PropertySet for properties not yet in any pset
                    owner_history = None
                    oh_list = self.model.by_type("IfcOwnerHistory")
                    if oh_list:
                        owner_history = oh_list[0]
                    
                    new_ifc_props = []
                    for prop_name, prop_value in props.items():
                        new_value = self.model.createIfcText(prop_value)
                        new_prop = self.model.createIfcPropertySingleValue(
                            prop_name, None, new_value, None
                        )
                        new_ifc_props.append(new_prop)
                        added_count += 1
                    
                    if new_ifc_props:
                        new_pset = self.model.createIfcPropertySet(
                            ifcopenshell.guid.new(),
                            owner_history,
                            pset_name,
                            None,
                            new_ifc_props
                        )
                        
                        self.model.createIfcRelDefinesByProperties(
                            ifcopenshell.guid.new(),
                            owner_history,
                            None,
                            None,
                            [element],
                            new_pset
                        )
            
            self.save_status.value = (
                f"<span style='color:green'>✅ Saved! Modified: <b>{modified_count}</b>, "
                f"Added: <b>{added_count}</b> properties for element "
                f"<b>{element.GlobalId[:12]}</b></span>"
            )
            
            # Refresh the properties display to show current state
            self._show_editable_properties(self.current_selected_full_name)
        
        except Exception as e:
            self.save_status.value = f"<span style='color:red'>❌ Error saving: {str(e)}</span>"
            import traceback
            traceback.print_exc()

    def _create_ifc_value_by_type(self, ifc_type, value_str):
        """
        Create an IFC value entity matching the original type.
        
        Parameters:
        -----------
        ifc_type : str
            The IFC type name (e.g., 'IfcText', 'IfcReal')
        value_str : str
            The string representation of the value
            
        Returns:
        --------
        IFC value entity or None
        """
        try:
            type_map = {
                "IfcText": lambda v: self.model.createIfcText(v),
                "IfcLabel": lambda v: self.model.createIfcLabel(v),
                "IfcIdentifier": lambda v: self.model.createIfcIdentifier(v),
                "IfcReal": lambda v: self.model.createIfcReal(float(v)),
                "IfcInteger": lambda v: self.model.createIfcInteger(int(v)),
                "IfcBoolean": lambda v: self.model.createIfcBoolean(v.lower() in ('true', '1', 'yes')),
                "IfcLengthMeasure": lambda v: self.model.createIfcLengthMeasure(float(v)),
                "IfcAreaMeasure": lambda v: self.model.createIfcAreaMeasure(float(v)),
                "IfcVolumeMeasure": lambda v: self.model.createIfcVolumeMeasure(float(v)),
                "IfcCountMeasure": lambda v: self.model.createIfcCountMeasure(float(v)),
                "IfcMassMeasure": lambda v: self.model.createIfcMassMeasure(float(v)),
                "IfcPositiveLengthMeasure": lambda v: self.model.createIfcPositiveLengthMeasure(float(v)),
                "IfcPlaneAngleMeasure": lambda v: self.model.createIfcPlaneAngleMeasure(float(v)),
                "IfcThermalTransmittanceMeasure": lambda v: self.model.createIfcThermalTransmittanceMeasure(float(v)),
            }
            
            creator = type_map.get(ifc_type)
            if creator:
                return creator(value_str)
            else:
                # Default fallback: try IfcText
                return self.model.createIfcText(value_str)
        
        except (ValueError, TypeError):
            return self.model.createIfcText(value_str)

    def _save_ifc_to_file(self, b):
        """Save the modified IFC model to a file (and offer download in Colab)."""
        try:
            import os
            output_filename = self.save_file_name.value.strip() or "modified_model.ifc"
            
            self.model.write(output_filename)
            full_path = os.path.abspath(output_filename)
            
            self.save_status.value = (
                f"<span style='color:green'>✅ IFC file saved: <b>{full_path}</b></span>"
            )
            
            # In Google Colab, offer file download
            try:
                from google.colab import files
                files.download(output_filename)
                self.save_status.value += (
                    "<br><span style='color:blue'>📥 Download started...</span>"
                )
            except ImportError:
                pass  # Not in Colab — file is saved locally
        
        except Exception as e:
            self.save_status.value = f"<span style='color:red'>❌ Error saving file: {str(e)}</span>"

    # -------------------------------------------------------------------------
    # Overview Table
    # -------------------------------------------------------------------------

    def _create_table(self):
        """Create the interactive overview table with QTO properties."""
        header_values = ["Storey", "Type", "Name", "GUID"]
        
        # Collect all QTO keys
        qto_keys_by_type = defaultdict(set)
        for storey_name, types in self.hierarchy.items():
            if self.filter_storey and self.filter_storey != 'All' and storey_name != self.filter_storey:
                continue
            for ifc_type, elements in types.items():
                if self.filter_ifc_type and self.filter_ifc_type != 'All' and ifc_type != self.filter_ifc_type:
                    continue
                for element in elements:
                    if GeometryExtractor.extract_custom_mesh_from_entity(element):
                        qto_props = GeometryExtractor.extract_qto_properties(element, self.model)
                        qto_keys_by_type[ifc_type].update(qto_props.keys())
        
        qto_keys = sorted(set().union(*qto_keys_by_type.values())) if qto_keys_by_type else []
        
        if qto_keys:
            header_values.extend(qto_keys)
        
        # Build table data
        cells_values = [[] for _ in header_values]
        row_colors = []
        current_row = 0
        
        for storey_name, types in self.hierarchy.items():
            if self.filter_storey and self.filter_storey != 'All' and storey_name != self.filter_storey:
                continue
            for ifc_type, elements in types.items():
                if self.filter_ifc_type and self.filter_ifc_type != 'All' and ifc_type != self.filter_ifc_type:
                    continue
                for element in elements:
                    if GeometryExtractor.extract_custom_mesh_from_entity(element):
                        element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                        full_name = f"{storey_name}/{ifc_type}/{element_name}"
                        
                        if full_name in self.visualizer.mesh_dict:
                            cells_values[0].append(storey_name)
                            cells_values[1].append(ifc_type)
                            cells_values[2].append(element_name)
                            cells_values[3].append(element.GlobalId[:8])
                            
                            qto_props = GeometryExtractor.extract_qto_properties(element, self.model)
                            for key in qto_keys:
                                value = qto_props.get(key, "-")
                                cells_values[header_values.index(key)].append(str(value))
                            
                            row_colors.append("#ffffff" if current_row % 2 == 0 else "#f0f0f0")
                            current_row += 1
        
        if not cells_values[0]:
            return go.FigureWidget(data=[go.Table(
                header=dict(values=["Message"], fill_color='#FF5733', font=dict(color='white')),
                cells=dict(values=[["No element matches the filters."]], align='center')
            )])
        
        # Create table as FigureWidget for click interactivity
        table_fig = go.FigureWidget(data=[go.Table(
            header=dict(
                values=header_values,
                fill_color='#4CAF50',
                font=dict(color='white', size=12),
                align='left'
            ),
            cells=dict(
                values=cells_values,
                fill_color=[row_colors],
                align='left',
                height=30
            )
        )])
        
        table_fig.update_layout(
            width=800,
            height=400,
            margin=dict(l=0, r=0, t=20, b=0)
        )
        
        # Table click handler
        def on_table_click(trace, points, selector):
            if points.point_inds:
                row_index = points.point_inds[0]
                if row_index < len(cells_values[0]):
                    full_name = (
                        f"{cells_values[0][row_index]}/{cells_values[1][row_index]}/"
                        f"{cells_values[2][row_index]}"
                    )
                    # Update dropdown
                    self.element_selector.unobserve(self._on_element_dropdown_change, names='value')
                    if full_name in [opt for opt in self.element_selector.options]:
                        self.element_selector.value = full_name
                    self.element_selector.observe(self._on_element_dropdown_change, names='value')
                    self._select_mesh(full_name)
        
        table_fig.data[0].on_click(on_table_click)
        
        return table_fig

    def _update_table(self):
        """Update the table display."""
        with self.table_output:
            self.table_output.clear_output()
            table = self._create_table()
            display(table)

    def _update_viewer(self):
        """Update the 3D viewer (only needed for non-FigureWidget fallback)."""
        if self.visualizer._is_figure_widget:
            # FigureWidget auto-updates; just sync visibility
            with self.visualizer.fig.batch_update():
                for trace in self.visualizer.fig.data:
                    if trace.name in self.visualizer.visibility:
                        trace.visible = self.visualizer.visibility[trace.name]
        else:
            # Fallback: would need Output widget redisplay (not used in normal flow)
            pass

    # -------------------------------------------------------------------------
    # Filters
    # -------------------------------------------------------------------------

    def _apply_filters(self, b):
        """Apply the selected filters to the visualization."""
        self.filter_storey = self.storey_dropdown.value
        self.filter_ifc_type = self.ifc_type_dropdown.value
        
        print(f"🔍 Applying filters: Storey={self.filter_storey}, IFC Type={self.filter_ifc_type}")
        
        # Update visibility based on filters
        if self.visualizer._is_figure_widget:
            with self.visualizer.fig.batch_update():
                for full_name in self.visualizer.mesh_dict:
                    parts = full_name.split('/')
                    storey = parts[0] if len(parts) > 0 else ''
                    ifc_type = parts[1] if len(parts) > 1 else ''
                    is_visible = (
                        (self.filter_storey == 'All' or storey == self.filter_storey) and
                        (self.filter_ifc_type == 'All' or ifc_type == self.filter_ifc_type)
                    )
                    self.visualizer.visibility[full_name] = is_visible
                    
                    # Update trace visibility
                    for trace in self.visualizer.fig.data:
                        if trace.name == full_name:
                            trace.visible = is_visible
                            break
                    
                    if full_name in self.all_checkboxes:
                        self.all_checkboxes[full_name].value = is_visible
        else:
            for full_name in self.visualizer.mesh_dict:
                parts = full_name.split('/')
                storey = parts[0] if len(parts) > 0 else ''
                ifc_type = parts[1] if len(parts) > 1 else ''
                is_visible = (
                    (self.filter_storey == 'All' or storey == self.filter_storey) and
                    (self.filter_ifc_type == 'All' or ifc_type == self.filter_ifc_type)
                )
                self.visualizer.visibility[full_name] = is_visible
                self.visualizer.mesh_dict[full_name].visible = is_visible
                
                if full_name in self.all_checkboxes:
                    self.all_checkboxes[full_name].value = is_visible
        
        self._update_table()
        self._update_element_selector()
        print("✅ 3D view, table, and element selector updated")

    # -------------------------------------------------------------------------
    # Visibility Accordion
    # -------------------------------------------------------------------------

    def _create_visibility_accordion(self):
        """Create the hierarchical visibility control accordion."""
        visibility_accordion = widgets.Accordion(children=[])
        visibility_titles = []
        
        for storey_name, types in self.hierarchy.items():
            if self.filter_storey and self.filter_storey != 'All' and storey_name != self.filter_storey:
                continue
            
            type_accordion = widgets.Accordion(children=[])
            type_titles = []
            
            for ifc_type, elements in types.items():
                if self.filter_ifc_type and self.filter_ifc_type != 'All' and ifc_type != self.filter_ifc_type:
                    continue
                
                element_checkboxes = []
                for element in elements:
                    if GeometryExtractor.extract_custom_mesh_from_entity(element):
                        element_name = element.Name or f"{element.is_a()}_{element.GlobalId[:8]}"
                        full_name = f"{storey_name}/{ifc_type}/{element_name}"
                        
                        if full_name in self.visualizer.mesh_dict:
                            checkbox = widgets.Checkbox(
                                value=self.visualizer.visibility.get(full_name, True),
                                description=element_name,
                                indent=False,
                                layout=widgets.Layout(width='auto')
                            )
                            checkbox.full_name = full_name
                            checkbox.observe(self._on_checkbox_change, names="value")
                            element_checkboxes.append(checkbox)
                            self.all_checkboxes[full_name] = checkbox
                
                if element_checkboxes:
                    select_all_checkbox = widgets.Checkbox(
                        value=True,
                        description=f"Select all ({len(element_checkboxes)} elements)",
                        indent=False,
                        style={'font_weight': 'bold'}
                    )
                    select_all_checkbox.related_checkboxes = element_checkboxes
                    select_all_checkbox.observe(self._on_select_all_change, names="value")
                    
                    type_container = widgets.VBox([
                        select_all_checkbox,
                        widgets.HTML("<hr style='margin: 5px 0;'>"),
                        *element_checkboxes
                    ])
                    
                    type_accordion.children += (type_container,)
                    type_titles.append(f"{ifc_type} ({len(element_checkboxes)})")
            
            if type_accordion.children:
                for i, title in enumerate(type_titles):
                    type_accordion.set_title(i, title)
                visibility_accordion.children += (type_accordion,)
                visibility_titles.append(f"{storey_name} ({len(type_titles)} types)")
        
        for i, title in enumerate(visibility_titles):
            visibility_accordion.set_title(i, title)
        
        return visibility_accordion

    def _on_checkbox_change(self, change):
        """Handle individual checkbox changes."""
        checkbox = change['owner']
        full_name = checkbox.full_name
        is_visible = change['new']
        
        self.visualizer.visibility[full_name] = is_visible
        
        if self.visualizer._is_figure_widget:
            with self.visualizer.fig.batch_update():
                for trace in self.visualizer.fig.data:
                    if trace.name == full_name:
                        trace.visible = is_visible
                        break
        else:
            self.visualizer.mesh_dict[full_name].visible = is_visible
            for i, trace in enumerate(self.visualizer.fig.data):
                if trace.name == full_name:
                    self.visualizer.fig.data[i].visible = is_visible
                    break
            self._update_viewer()
        
        if is_visible:
            self._select_mesh(full_name)
        else:
            if self.visualizer.selected_mesh[0] == full_name:
                self._deselect_current()

    def _on_select_all_change(self, change):
        """Handle 'select all' checkbox changes."""
        select_all_checkbox = change['owner']
        new_value = change['new']
        
        if self.visualizer._is_figure_widget:
            with self.visualizer.fig.batch_update():
                for checkbox in select_all_checkbox.related_checkboxes:
                    if checkbox.full_name in self.visualizer.mesh_dict:
                        checkbox.value = new_value
                        self.visualizer.visibility[checkbox.full_name] = new_value
                        for trace in self.visualizer.fig.data:
                            if trace.name == checkbox.full_name:
                                trace.visible = new_value
                                break
        else:
            for checkbox in select_all_checkbox.related_checkboxes:
                if checkbox.full_name in self.visualizer.mesh_dict:
                    checkbox.value = new_value
                    self.visualizer.visibility[checkbox.full_name] = new_value
                    self.visualizer.mesh_dict[checkbox.full_name].visible = new_value
                    for i, trace in enumerate(self.visualizer.fig.data):
                        if trace.name == checkbox.full_name:
                            self.visualizer.fig.data[i].visible = new_value
                            break
            self._update_viewer()

    def _expand_all_accordions(self, accordion):
        """Recursively expand all accordions."""
        for i in range(len(accordion.children)):
            accordion.selected_index = i
            child = accordion.children[i]
            if hasattr(child, 'children') and isinstance(child.children[0], widgets.Accordion):
                self._expand_all_accordions(child.children[0])

    def _collapse_all_accordions(self, accordion):
        """Recursively collapse all accordions."""
        accordion.selected_index = None
        for child in accordion.children:
            if hasattr(child, 'children'):
                for subchild in child.children:
                    if isinstance(subchild, widgets.Accordion):
                        subchild.selected_index = None
