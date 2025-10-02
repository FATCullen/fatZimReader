import urwid
from libzim.reader import Archive
from libzim.search import Query, Searcher
from bs4 import BeautifulSoup
from urllib import parse
import textwrap

class ZimManager:
    """Handles ZIM file operations"""

    def __init__(self, zim_path):
        self.archive = Archive(zim_path)
        self.searcher = Searcher(self.archive)
    
    def search(self, query_string, max_results=20):
        """Search ZIM file and return results"""
        query = Query().set_query(query_string)
        results = self.searcher.search(query)
        count = results.getEstimatedMatches()
        return list(results.getResults(0, min(max_results, count)))
    
    def get_article(self, path):
        """Retrieve article content by path"""
        try:
            entry = self.archive.get_entry_by_path(path)
            html_content = bytes(entry.get_item().content).decode("UTF-8")
            return entry.title, html_content
        except Exception as e:
            return None, f"Error: {e} {path}"


class ArticleParser:
    """Converts HTML to terminal-friendly format"""
    
    def __init__(self, html_content):
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.links = []
        self.text_widgets = []
        self.link_widgets = []
        self.max_width = 80
    
    def parse(self, max_width=80):
        """Parse HTML and extract text with links"""

        self.max_width = max_width

        content = self.soup.find('div', {'id': 'mw-content-text'})
        if not content:
            content = self.soup.find('body')
        
        if not content:
            return [urwid.Text("Could not parse article content")]
        
        for tag in content.find_all(['script', 'style', 'sup']):
            tag.decompose()
        
        self.text_widgets = []
        self.links = []
        self.link_widgets = []
        self._process_element(content)
        
        return self.text_widgets
    
    def _process_element(self, element):
        """Recursively process HTML elements"""
        for child in element.children:
            if isinstance(child, str):
                text = child.strip()
                if text:
                    self.text_widgets.append(urwid.Text(text))
            elif child.name == 'p':
                self._process_paragraph(child)
                self.text_widgets.append(urwid.Divider())
            elif child.name in ['h1', 'h2', 'h3', 'h4']:
                level = int(child.name[1])
                text = child.get_text().strip()
                self.text_widgets.append(urwid.Divider())
                self.text_widgets.append(
                    urwid.Text(('heading', f"{'#' * level * 2} {text} {'#' * level * 2}"))
                )
                self.text_widgets.append(urwid.Divider())
            elif child.name in ['ul', 'ol']:
                self._process_list(child)
            elif child.name == 'div':
                self._process_element(child)
            elif child.name == 'table':
                self._process_table(child)
            elif child.name == 'a':
                self._process_link(child)

    def _process_link(self, link_elem):
        """Process links"""
        href = link_elem.get('href', '')
        is_external = (
            href.startswith('http://') or 
            href.startswith('https://') or 
            href.startswith('//') or
            href.startswith('#') or
            href.startswith('mailto:')
        )
        
        if not is_external:
            link_path = href.split('#')[0]
            link_path = parse.unquote(link_path.replace('../', '').replace('/wiki/', '').replace(' ', '_'))
            if link_path:
                link_text = link_elem.get_text().strip()
                if link_text:
                    link_index = len(self.links)
                    self.links.append((link_path, link_text))          
                    link_widget = SelectableText(('link', f"→ [{link_text}]"))
                    link_widget.link_path = link_path
                    link_widget.link_index = link_index
                    link_mapped = urwid.AttrMap(link_widget, 'link', focus_map='link_focus')
                    link_mapped.link_path = link_path
                    link_mapped.link_index = link_index
                    self.text_widgets.append(link_mapped)
                    self.link_widgets.append(link_mapped)
    
    def _process_paragraph(self, para):
        """Process paragraph with inline links"""
        para_text = para.get_text().strip()
        
        if para_text:
            self.text_widgets.append(urwid.Text(para_text))
            
            for link_elem in para.find_all('a', href=True):
                self._process_link(link_elem)
    
    def _process_list(self, list_elem):
        """Process lists"""
        for li in list_elem.find_all('li', recursive=False):
            text = li.get_text().strip()
            if text:
                self.text_widgets.append(urwid.Text(f"  • {text}"))
        for link_elem in list_elem.find_all('a', href=True):
                self._process_link(link_elem)

    def _process_table(self, element):
        """Process <table> HTML element into a formatted ASCII/Unicode table"""
        rows = []
        for row_el in element.find_all("tr"):
            row = []
            for cell in row_el.find_all(["td", "th"]):
                text = cell.get_text(" ", strip=True)
                colspan = min(int(cell.get("colspan", 1)), 5)
                rowspan = min(int(cell.get("rowspan", 1)), 5)
                row.append((text, colspan, rowspan))
            rows.append(row)

        if not rows:
            return [urwid.Text("(empty table)")]

        grid = []
        occupied = {}
        for r_idx, row in enumerate(rows):
            grid_row = []
            c_idx = 0
            for text, colspan, rowspan in row:
                while (r_idx, c_idx) in occupied:
                    grid_row.append(occupied[(r_idx, c_idx)][0])
                    occupied[(r_idx, c_idx)][1] -= 1
                    if occupied[(r_idx, c_idx)][1] <= 0:
                        del occupied[(r_idx, c_idx)]
                    c_idx += 1

                cell_text = text
                grid_row.append(cell_text)

                for _ in range(1, colspan):
                    grid_row.append("")

                if rowspan > 1:
                    for rr in range(1, rowspan):
                        occupied[(r_idx+rr, c_idx)] = [cell_text, rowspan-rr]

                c_idx += colspan
            grid.append(grid_row)

        num_cols = max(len(r) for r in grid)
        for row in grid:
            while len(row) < num_cols:
                row.append("")

        term_width = getattr(self, 'max_width', 80)
        col_widths = [0] * num_cols
        for c in range(num_cols):
            longest_word = 1
            longest_cell = 1
            for r in range(len(grid)):
                cell = str(grid[r][c])
                if not cell:
                    continue
                longest_cell = max(longest_cell, len(cell))
                for word in cell.split():
                    longest_word = max(longest_word, len(word))
            col_widths[c] = max(longest_word, min(longest_cell, 30))

        total = sum(col_widths) + (3 * (num_cols - 1)) + 2
        if total > term_width:
            scale = (term_width - (3 * (num_cols - 1)) - 2) / sum(col_widths)
            col_widths = [max(5, int(w * scale)) for w in col_widths]

        def wrap_cell_text(text, width):
            if not text:
                return [""]
            words = text.split()
            wrapped_lines = []
            for word in words:
                if len(word) <= width:
                    wrapped_lines.append(word)
                else:
                    chunks = textwrap.wrap(word, width-1)
                    chunks = [c + "-" if i < len(chunks)-1 else c
                            for i, c in enumerate(chunks)]
                    wrapped_lines.extend(chunks)
            return textwrap.wrap(" ".join(wrapped_lines), width) or [""]

        wrapped_grid = []
        for row in grid:
            wrapped_row = []
            for c, cell in enumerate(row):
                wrapped_row.append(wrap_cell_text(str(cell), col_widths[c]))
            wrapped_grid.append(wrapped_row)

        def make_separator(left, mid, right, fill="─"):
            parts = []
            for w in col_widths:
                parts.append(fill * (w + 2))
            return left + mid.join(parts) + right

        lines = []
        lines.append(make_separator("┌", "┬", "┐"))
        for r, row in enumerate(wrapped_grid):
            row_height = max(len(cell) for cell in row)
            for line_idx in range(row_height):
                line_parts = []
                for c, cell in enumerate(row):
                    content = cell[line_idx] if line_idx < len(cell) else ""
                    line_parts.append(" " + content.ljust(col_widths[c]) + " ")
                lines.append("│" + "│".join(line_parts) + "│")

            if r == 0:
                lines.append(make_separator("├", "┼", "┤"))
            elif r < len(wrapped_grid)-1:
                lines.append(make_separator("├", "┼", "┤"))

        lines.append(make_separator("└", "┴", "┘"))

        for l in lines:
            self.text_widgets.append(urwid.Text(l[:self.max_width]))
        for link_elem in element.find_all('a', href=True):
                self._process_link(link_elem)

class SelectableText(urwid.Text):
    """Text widget that can be selected with keyboard"""
    
    def selectable(self):
        return True
    
    def keypress(self, size, key):
        return key


class WikiApp:
    """Main application controller"""
    
    MODE_SEARCH = 'search'
    MODE_RESULTS = 'results'
    MODE_ARTICLE = 'article'
    
    def __init__(self, zim_path):
        self.zim = ZimManager(zim_path)
        self.history = []
        self.current_links = []
        self.current_link_index = 0
        self.link_widgets = []
        self.mode = self.MODE_SEARCH
        self.search_results = []
        self.result_widgets = []
        
        self.palette = [
            ('heading', 'yellow,bold', 'default'),
            ('link', 'light cyan,underline', 'default'),
            ('link_focus', 'black', 'light cyan'),
            ('search_box', 'white', 'dark blue'),
            ('title', 'white,bold', 'dark blue'),
            ('status', 'white', 'dark gray'),
        ]
        
        self.setup_ui(zim_path)
    
    def setup_ui(self, zim_path):
        """Initialize the UI"""
        self.search_edit = urwid.Edit("Search: ")
        search_box = urwid.AttrMap(
            urwid.LineBox(self.search_edit, title="fatZimReader"),
            'search_box'
        )
        
        self.content_walker = urwid.SimpleFocusListWalker([
            urwid.Text("\nWelcome to fatZimReader, a fully offline, terminal based, zim file browser"),
            urwid.Text("Created by Finn Cullen (fatcullen)\n"),
            urwid.Text("FILE INFO:"),
            urwid.Text(f"  Title: {zim_path}"),
            urwid.Text(f"  File Size: {self.zim.archive.filesize / (1024*1024):.2f} MB"),
            urwid.Text(f"  Main Entry: {self.zim.archive.main_entry.title}"),
            urwid.Text(f"  Article Count: {self.zim.archive.article_count}"),

        ])
        self.content_list = urwid.ListBox(self.content_walker)
        
        self.status_text = urwid.Text("Mode: Start | /: Search | r: Random | q: Quit")
        status_bar = urwid.AttrMap(self.status_text, 'status')
        
        self.frame = urwid.Frame(
            header=search_box,
            body=self.content_list,
            footer=status_bar
        )
    
    def update_status(self, text):
        """Update status bar"""
        self.status_text.set_text(text)
    
    def show_search_results(self, query):
        """Display search results"""
        self.search_results = self.zim.search(query)
        
        self.content_walker.clear()
        self.content_walker.append(
            urwid.Text(f"\nFound {len(self.search_results)} results for '{query}':\n")
        )
        
        self.result_widgets = []
        for i, result in enumerate(self.search_results):
            text = SelectableText(f"{i+1}. {result}")
            mapped = urwid.AttrMap(text, None, focus_map='link_focus')
            mapped.result_path = result
            self.content_walker.append(mapped)
            self.result_widgets.append(mapped)
        
        if len(self.content_walker) > 1:
            self.content_walker.focus_position = 1
        
        self.mode = self.MODE_RESULTS
        self.update_status("Mode: Results | ↑↓: Navigate | ↵ or →: Select | /: Search | r: Random | q: Quit")
    
    def load_article(self, path):
        """Load and display an article"""
        title, html = self.zim.get_article(path)
        
        if not title:
            self.content_walker.clear()
            self.content_walker.append(urwid.Text(html))
            return
        
        cols, _ = self.loop.screen.get_cols_rows()
        parser = ArticleParser(html)
        widgets = parser.parse(max_width=cols - 2)
        self.current_links = parser.links
        self.link_widgets = parser.link_widgets
        self.current_link_index = 0
        
        self.content_walker.clear()
        self.content_walker.append(
            urwid.Text(('title', f"\n{title}\n"))
        )
        self.content_walker.append(urwid.Divider('='))
        self.content_walker.extend(widgets)
        
        if len(self.content_walker) > 0:
            self.content_walker.focus_position = 0
        
        self.history.append(path)
        self.mode = self.MODE_ARTICLE
        
        link_count = len(self.current_links)
        self.update_status(
            f"Mode: Article | {link_count} links | ↑↓: Navigate | ↵ or →: Follow | ←: Back | Space: Page Down | /: Search | r: Random | q: Quit"
        )
    
    def handle_input(self, key):
        """Handle keyboard input"""
        if key == 'q':
            raise urwid.ExitMainLoop()
        elif key == '/':
            self.mode = self.MODE_SEARCH
            self.frame.focus_position = 'header'
            self.update_status("Mode: Search | Enter to search")
            return
        elif key == 'r':
            self.load_article(self.zim.archive.get_random_entry().path)
        
        if self.mode == self.MODE_SEARCH:
            if key == 'enter':
                query = self.search_edit.get_edit_text()
                if query:
                    self.show_search_results(query)
                    self.frame.focus_position = 'body'
        
        elif self.mode == self.MODE_RESULTS:
            if key == 'enter' or key == 'right':
                focused_widget, focus_pos = self.content_walker.get_focus()
                if hasattr(focused_widget, 'result_path'):
                    self.load_article(focused_widget.result_path)
        
        elif self.mode == self.MODE_ARTICLE:
            if key == 'left':
                if len(self.history) > 1:
                    self.history.pop()
                    self.load_article(self.history[-1])
                    self.history.pop()
            elif key == 'right' or key == 'enter':
                focused_widget, focus_pos = self.content_walker.get_focus()
                
                if hasattr(focused_widget, 'link_path'):
                    self.load_article(focused_widget.link_path)
            elif key == 'up' or key == 'down':
                if not self.link_widgets:
                    return
                
                focused_widget, focus_pos = self.content_walker.get_focus()
                
                current_link_idx = None
                for i, link_widget in enumerate(self.link_widgets):
                    if focused_widget == link_widget:
                        current_link_idx = i
                        break
                
                if key == 'up':
                    if current_link_idx is not None and current_link_idx > 0:
                        next_idx = current_link_idx - 1
                    else:
                        next_idx = len(self.link_widgets) - 1
                else:
                    if current_link_idx is not None and current_link_idx < len(self.link_widgets) - 1:
                        next_idx = current_link_idx + 1
                    else:
                        next_idx = 0
                
                self._focus_link(next_idx)
                return
            elif key == ' ':
                size = self.loop.screen.get_cols_rows()
                rows = size[1] - 7
                for _ in range(rows):
                    self.content_list.keypress(size, 'down')
                return
    
    def _widget_in_tree(self, focused, target):
        """Check if focused widget is the target or contains it"""
        if focused == target:
            return True
        return False
    
    def _focus_link(self, link_index):
        """Focus on a specific link by index"""
        if 0 <= link_index < len(self.link_widgets):
            target_link = self.link_widgets[link_index]
            
            for i, widget in enumerate(self.content_walker):
                if widget == target_link:
                    self.content_walker.focus_position = i
                    self.content_list.set_focus_valign('middle')
                    return
    
    def run(self):
        """Start the application"""
        self.loop = urwid.MainLoop(
            self.frame,
            palette=self.palette,
            unhandled_input=self.handle_input
        )
        
        self.frame.focus_postion = 'footer'
        
        self.loop.run()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python fatZimReader.py <path_to_zim_file>")
        sys.exit(1)
    
    app = WikiApp(sys.argv[1])
    app.run()
